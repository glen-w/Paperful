# Workflows

Operator sequences for one collection slice. A **run config** (also called a
**profile**) saves that slice. `paperful all` runs the usual chain in one
process. Individual commands stay available and can still be chained with
`&&`.

This is not a scheduler and not a GUI. There is no cron helper and no saved
dashboard. Recipes below are copy-paste commands.

## Do not conflate

| Word | What it is | Where it lives |
| --- | --- | --- |
| **Run config / profile** | SCOPE plus fetch/write policy for a repeated slice (collection, years, item types, `try_all`, …) | `[profiles.*]` in `config.toml`, or `profiles/<name>.toml` beside that file |
| **`all`** | One command that runs a fixed sequence of existing verbs | `paperful all` |
| **`--preset eoi`** | Source *policy*: open access plus campus EZProxy, no Scholar, no Sci-Hub | CLI flag or `preset` in a profile |
| **Playbook** | URL → PDF rule (`rewrite` / `scrape` / `synthesize`), hand-written or learned from fetch wins | `[[grey_playbooks]]`, `packs/*.toml`, `packs/learned.toml` |
| **Pack** | Witness for one *executed* sequence. Lists child reports. Not a template you re-run | `state/packs/<id>.json` |

Grey-lit `packs/` and run-config `profiles/` are different directories.
`state/packs/` is the witness, and it is excluded from backups of the
checkout. Profiles sit next to `config.toml` so they are kept with config.

## 1. The shell sequence

This is the pattern `all` copies. `SCOPE` is shared so every verb sees the
same collection, years, and item types. `run` adds fetch flags. `fix-metadata`
and `summarize` add `--apply`.

```sh
SCOPE=(-C BBNJ -T journalArticle --year-from 2021 --year-to 2026)

uv run paperful gaps "${SCOPE[@]}" \
  && uv run paperful run "${SCOPE[@]}" --try-all --retry-failed --upgrade-linked \
  && uv run paperful lint "${SCOPE[@]}" \
  && uv run paperful fix-metadata "${SCOPE[@]}" --apply \
  && uv run paperful summarize "${SCOPE[@]}" --apply
```

`&&` stops on the first non-zero exit. `lint` is not `--strict`, so findings
do not abort the chain. `summarize` needs `[llm].enabled`; if the model is
off, that step fails and the earlier steps have already finished.

The same flags work one verb at a time. See [Commands](commands.md#scope-filters).

## 2. Same chain, one process

```sh
uv run paperful all -C BBNJ -T journalArticle --year-from 2021 --year-to 2026
```

Default steps, in order:

1. `gaps`
2. `run --try-all --retry-failed --upgrade-linked`
3. `lint` (not `--strict`)
4. `fix-metadata --apply`
5. `summarize --apply`

Those run flags and `--apply` are the builtin `all` policy. They apply when
the command is `all` and the profile does not set the key. `paperful run`
alone does not turn `--try-all` on.

The chain stops on the first failing step, same as `&&`.

### Dry run

```sh
uv run paperful all -C BBNJ -T journalArticle --year-from 2021 --year-to 2026 --dry-run
```

| Step | What `--dry-run` does |
| --- | --- |
| `gaps` | Counts, as usual |
| `run` | Would-hit table. No downloads |
| `lint` | Read-only findings |
| `fix-metadata` | Proposes patches. Does not pass `--apply` |
| `summarize` | **Skipped.** Summarize has no dry-run and the default destination writes notes |

`run --dry-run` exits before it writes `state/runs/…-run.json`, so an
auto-opened pack may list `gaps`, `lint`, and `fix-metadata` and omit `run`.
That matches a standalone dry run.

### LLM off

If `[llm].enabled` is false, `all` skips `summarize` and continues. The line
says `llm.enabled is false`. Pass `--require-summarize` (or set
`require_summarize = true` in the profile) to exit 1 instead.

`all --dry-run` skips `summarize` even when the LLM is on.

### Pack

If no pack is open, `all` opens one (label: `--label`, otherwise the profile
name, otherwise `all`) and closes it when the command finishes, including
when a step fails. If a pack is already open, `all` appends to it and leaves
it open.

`PAPERFUL_PACK=off` still keeps each child report out of a pack. `all` does
not open one in that case.

`paperful pack show` reads the witness. It does not re-run the steps.

### Narrow the chain

```sh
uv run paperful all -C BBNJ --steps gaps,run,lint
uv run paperful all -C BBNJ --skip summarize
```

`--steps` replaces the list. `--skip` removes names from it. Unknown names
exit 1. Optional names you can add, which are **not** in the default chain:
`snapshot`, `dedupe`, `synthesize`, `ocr`.

`dedupe` and `restore` honor `apply` only when `all` is running them. A
direct `paperful dedupe --profile …` does not trash unless you also pass
`--apply`.

## 3. Save the slice

Profiles live **beside** `config.toml`, never under `state/`.

```sh
uv run paperful profile save bbnj-journal \
  -C BBNJ -T journalArticle \
  --year-from 2021 --year-to 2026 \
  --try-all --retry-failed --upgrade-linked \
  --apply \
  --description "BBNJ journal articles 2021–2026"
```

That writes `profiles/bbnj-journal.toml` next to the config file in use
(`--config` if you passed it, otherwise the file Paperful loaded). It does
not rewrite `config.toml`. A second save exits 1 until `--force`.

The same keys can live in config instead of a file:

```toml
[profiles.bbnj-journal]
description = "BBNJ journal articles 2021–2026"
collections = ["BBNJ"]
types = ["journalArticle"]
year_from = 2021
year_to = 2026
try_all = true
retry_failed = true
upgrade_linked = true
apply = true
```

If both exist, the file overlays the table key by key. `collections` in the
file replaces `collections` in the table; keys only in the table remain.

Then:

```sh
uv run paperful all --profile bbnj-journal
uv run paperful profile list
uv run paperful profile show bbnj-journal
```

`profile show` prints the merge **`paperful all` would use**, including
builtin defaults the file left out. `profile show` with no name prints those
defaults alone.

A one-off file that is not in `profiles/` works too:

```sh
uv run paperful all -f ./bbnj-journal.toml
```

`-f` / `--run-config` overlays `--profile` when both are set.

### Use the profile on one verb

`--profile` works on `gaps`, `run`, `lint`, `fix-metadata`, `summarize`,
`ocr`, `dedupe`, `snapshot`, `restore`, and `synthesize`. A profile that only stores
SCOPE does not turn on `try_all` for a bare `run`:

```sh
uv run paperful gaps --profile bbnj-journal \
  && uv run paperful run --profile bbnj-journal \
  && uv run paperful lint --profile bbnj-journal \
  && uv run paperful fix-metadata --profile bbnj-journal \
  && uv run paperful summarize --profile bbnj-journal
```

Put `try_all`, `retry_failed`, and `upgrade_linked` in the profile if `run`
should use them without extra flags. `apply = true` makes
`fix-metadata --profile` and `summarize --profile` write. It does not make
`dedupe --profile` trash.

Turn a saved bool off for one invocation:

```sh
uv run paperful run --profile bbnj-journal --no-try-all
uv run paperful all --profile bbnj-journal --no-apply
```

Pairs: `--try-all/--no-try-all`, `--retry-failed/--no-retry-failed`,
`--upgrade-linked/--no-upgrade-linked`, `--apply/--no-apply`,
`--library/--no-library`. Passing `-C` replaces the profile's collections
and clears `library` unless you also pass `--library`.

## Precedence

1. Builtin `all` policy (steps, try-all, retry-failed, upgrade-linked, apply) — **only for `all` and `profile show`**
2. `[profiles.*]` in `config.toml`
3. `profiles/<name>.toml` beside that config (same name overlays the table)
4. `--profile NAME` or `-f` / `--run-config FILE`
5. Explicit CLI flags

CLI always wins for a key you passed. Omitted flags keep the profile value,
then the builtin `all` value when the command is `all`.

## Docker

`profiles/` is next to `config.toml` on the data dir (`/data` in Compose).
Create it beside config, not inside the image:

```sh
mkdir -p ../paperful-data/profiles
docker compose run --rm paperful all --profile bbnj-journal --dry-run
```

Same commands as `uv run`. Headed `session login` stays on the host. See
[Docker](docker.md).

## 4. Deep collection pass (example template)

Operator recipe for one collection slice: dedupe, aggressive PDF fetch
(including the browser-agent lane), metadata write-back, grounded summaries,
then manual handoff for whatever automation missed. Replace placeholders with
your collection path (name or `parent/subcollection`), profile name, and pack
label. Subcollections are included automatically when you pass a parent path.

**Prerequisites:** Zotero 10+ with write API, a real Unpaywall `email`,
`[llm].enabled` for `summarize` and the auto `browser_agent` lane on `run`,
`uv sync --extra llm --extra browser-agent` (Python 3.11+), and headed
`paperful session login ezproxy` / `scholar` when you use those sources.
Optional: `[inbox].dir` so `--handoff tabs` can continue into inbox watch.
Campus-only policy: add `--preset eoi` on `run` / `all`.

`paperful all` does **not** pass `--handoff` to its internal `run` step.
Use the shell chain below (or a second `run` / `gaps` with `--handoff`) for
tab or walk handoff.

Review duplicates before merging:

```sh
uv run paperful dedupe -C COLLECTION --dry-run
# read state/dedupe-packs/*.md
uv run paperful dedupe -C COLLECTION --apply
# title+year merges (optional):
uv run paperful dedupe -C COLLECTION --apply --apply-medium
```

One-shot chain (dedupe → fetch with relogin + browser agent → lint → metadata
→ summarize → sequential handoff for stragglers). Add year/type filters to
`SCOPE` when you need them (see [scope filters](commands.md#scope-filters)):

```sh
SCOPE=(-C COLLECTION)
# SCOPE=(-C COLLECTION -T TYPE --year-from YYYY --year-to YYYY)

uv run paperful pack open --label PACK_LABEL

uv run paperful dedupe "${SCOPE[@]}" --apply && \
uv run paperful gaps "${SCOPE[@]}" && \
uv run paperful run "${SCOPE[@]}" \
  --try-all --retry-failed --upgrade-linked \
  --browser-agent \
  --handoff tabs && \
uv run paperful lint "${SCOPE[@]}" && \
uv run paperful fix-metadata "${SCOPE[@]}" --apply && \
uv run paperful summarize "${SCOPE[@]}" --apply && \
uv run paperful gaps "${SCOPE[@]}" --list-missing --handoff walk

uv run paperful pack close
```

Same policy as `all`, but with dedupe first and explicit handoff on a
standalone `run`:

```sh
uv run paperful all -C COLLECTION \
  --steps dedupe,gaps,run,lint,fix-metadata,summarize \
  --apply --browser-agent
# then, for remaining misses:
uv run paperful gaps -C COLLECTION --list-missing --handoff walk
```

Handoff modes: `tabs` (batch open, optional inbox watch after tabs),
`watch` (tabs then poll `[inbox].dir`), `walk` (one URL at a time via
`[gaps].downloads_dir`). See [Sources](sources.md) (manual handoff after
soft blocks).

Save the slice for reruns (`handoff` is still a separate step):

```sh
uv run paperful profile save PROFILE_NAME \
  -C COLLECTION \
  --try-all --retry-failed --upgrade-linked \
  --apply \
  --steps dedupe,gaps,run,lint,fix-metadata,summarize \
  --description "DESCRIPTION"

uv run paperful all --profile PROFILE_NAME --browser-agent
uv run paperful gaps -C COLLECTION --list-missing --handoff walk
```

Dry-run the automated half first:

```sh
uv run paperful all -C COLLECTION \
  --steps dedupe,gaps,run,lint,fix-metadata,summarize \
  --apply --browser-agent --dry-run
```

(`summarize` is skipped; dedupe and `run` do not apply merges or downloads.)

## 5. Research pack (cited works → parents → PDFs)

Cited inside collection PDFs, not already in the library. Always dry-run the
gap pack and `ingest-dois` classify before `--apply`. Then `run` (or inbox)
fills PDFs.

```sh
docker compose run --rm paperful refs gap -C BBNJ
# read state/refs-gaps/*/pack.md
docker compose run --rm paperful ingest-dois --from-pack state/refs-gaps/<stamp> -C BBNJ
docker compose run --rm paperful ingest-dois --from-file state/refs-gaps/<stamp>/dois.txt -C BBNJ --apply --tag bbnj
docker compose run --rm paperful run -C BBNJ
docker compose run --rm paperful inbox drain    # optional: PDFs dropped into [inbox].dir
```

Contributors: the same verbs with `uv run paperful …`.

## What this is not

- Not a workflow engine. Steps are a list, not a graph.
- Not Rollup's cron, and not TranscriptX's saved GUI profiles.
- Not a grey-lit playbook. URL → PDF rules stay in `[[grey_playbooks]]`.
- Not a pack. A pack records one run; a profile is the input you can run again.
