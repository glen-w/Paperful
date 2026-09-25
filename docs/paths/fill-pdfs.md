# Path: fill missing PDFs

**Who:** you already have a Zotero library with gaps.  
**Goal:** PDFs under `out/`, attached into Zotero when the local API allows it.

Finish [Quick start](../start/quickstart.md) first (`doctor` green, `collections`
lists your libraries).

## Steps

1. Pick a **small** collection from `collections` (or create a test one).
2. List gaps:

```sh
docker compose run --rm paperful gaps --collection interesting
```

3. Dry-run a fetch (no downloads):

```sh
docker compose run --rm paperful run --collection interesting --dry-run
```

4. Fetch for real. Open access first. Optional academic recipe (OA + campus
   EZProxy policy, no Scholar, no Sci-Hub):

```sh
docker compose run --rm paperful run --collection interesting
# or:
docker compose run --rm paperful run --collection interesting --preset eoi
```

5. Inspect the last run:

```sh
docker compose run --rm paperful report
```

6. If downloads landed but attach was deferred (older Zotero, or attach
   approval pending), upgrade/approve then:

```sh
docker compose run --rm paperful attach --collection interesting
```

Narrow with `--year-from` / `--year-to` and `--type` / `-T` when the
collection is large. Details: [Commands — scope filters](../reference/commands.md#scope-filters).

## Campus fork (EZProxy)

For recent paywalled papers your library subscribes to, finish
[Campus EZProxy](../howto/ezproxy.md) **before** a big run: set
`ezproxy_base`, run `paperful session login ezproxy` **on the host**, verify,
then `run --retry-failed` on the same collection.

## Defer for later

- `paperful all` and saved profiles — [Workflows](../howto/workflows.md)
- Optional local LLM — [LLM](../howto/llm.md)
- Sci-Hub / Scholar opt-in — [Sci-Hub](../howto/scihub.md), [Sessions](../howto/sessions.md)
- Mendeley / EndNote — seeking testers; Zotero is the path this page teaches

## Related

- [Source routing](../reference/sources.md)
- [Research operators](../howto/research-ops.md) — email, campus use, provenance
- [Quiet mirror](quiet-mirror.md) — the `out/` tree this path writes into
