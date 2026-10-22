# Keepup (alert loop and what cites)

**Status:** shipped as CLI. Paperful does not schedule runs — point cron,
launchd, or a systemd user timer at `keepup run`. No email.

Keepup closes the loop after topic watches and author lists: poll → digest →
create parents into `-C` → post-ingest briefing → Wanted / `paperful run` for
PDFs. It also ships a configurable-interval **what cites my collection**
source.

## Save a job

```text
# Topic watch + people list + citers of -C
paperful keepup save field \
  -C Ocean/BBNJ \
  --watch bbnj \
  --authorwatch field-people \
  --source cites \
  --interval-days 7

# Citers only
paperful keepup save bbnj-cites -C Ocean/BBNJ --source cites --interval-days 7
```

Ledger: `state/keepup/<name>/` (`job.json`, `inbox.jsonl`, `seen.json`,
`applied.json`, `muted.json`, `digest.md`, `ingested.md`).

Default interval is `[keepup].interval_days` (7). Per-job `--interval-days`
overrides. `0` means every `keepup run` is due.

## Run

```text
paperful keepup run field              # poll if due; write digest.md
paperful keepup run field --force      # ignore interval
paperful keepup run field --apply      # poll then create parents
paperful keepup digest field
paperful keepup apply field            # dry-run
paperful keepup apply field --apply
paperful keepup dismiss field --doi 10.1000/x
```

First run is a **baseline**: advances source cursors / records current citers
as seen, proposes nothing. Later runs append unseen proposals to the keepup
inbox.

`watch` and `authorwatch` sources still use their own ledgers
(`state/snowball/watches/…`, `state/authorwatch/…`). Keepup merges pending
inbox rows and, on `--apply`, marks nested `applied.json` too.

## What cites

`--source cites` resolves DOIs in `-C`, then OpenAlex `filter=cites:` per seed
with `from_created_date` after the baseline. Overlap ranking yields a why line
such as `cites 3 of your papers (Title A; Title B)`. Caps:
`--per-seed-limit` (default 20) and `--max-candidates` (default 100).

## Pieces without keepup

| Verb | Role |
| --- | --- |
| `snowball watch run` / `digest` | Topic frontier only |
| `snowball watch apply -C … [--apply]` | Inbox → parents + `ingested.md` |
| `authorwatch run` / `digest` / `apply` | People list twin |

Digest `--apply -C` on snowball still only files a
`paperful:frontier-briefing` note. Parent creates stay on `watch apply` /
`keepup apply`.

## Schedule it yourself

```text
15 7 * * 1 cd /path/to/library && uv run paperful keepup run field --apply
```

Compose:

```text
15 7 * * 1 cd /path/to/paperful && docker compose run --rm paperful keepup run field --apply
```

If cron fires daily but `interval_days = 7`, early runs exit 0 with
`skipped · next due in N day(s)` unless `--force`.

## Related

- [Snowball watch](snowball.md#watch)
- [Authorwatch](authorwatch.md)
- [Roadmap — Keeping up](ROADMAP.md#after-110-keeping-up)
