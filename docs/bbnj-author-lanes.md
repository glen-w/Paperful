# BBNJ author-site + authorwatch (dogfood)

Harden the `author_site` grey lane and `authorwatch` on a **real** library
slice. Paperful’s Zotero path is `ocean/BBNJ` (Ocean → BBNJ). **`-C BBNJ`
alone will not resolve** that collection.

This is operator dogfood, not a 1.0 blocker. See [authorwatch](authorwatch.md),
[workflows § field author packs](workflows.md#6-field-author-packs-corpus-frequency--author_site),
and [research-pack](research-pack.md).

## Collections

| Role | `-C` / `--collection` | Notes |
| --- | --- | --- |
| **Production slice** | `ocean/BBNJ` | ~1300 items (authors report 2026-10-06). Do not dump authorwatch applies here. |
| **Dogfood slice** | `ocean/BBNJ-test` | Sibling under Ocean. Membership copy of a **small** `ocean/BBNJ` subset, plus optional authorwatch creates. Safe to `--apply`. |
| **Authorwatch landing (optional)** | `ocean/BBNJ-test` | Same test collection; tags `paperful-authorwatch` / `from-<list>`. |

Pack slug from `authors --apply` is the collection path with `/` → `-`:
`ocean-bbnj` (production) and `ocean-bbnj-test` (dogfood). Promote the slug
you intend the fetch lane to use:

```sh
paperful snowball packs promote ocean-bbnj        # production
paperful snowball packs promote ocean-bbnj-test   # dogfood
```

`author_site` is **not** in `DEFAULT_SOURCES`. The lane is appended when a
**promoted** pack has `listing_url` / `base_host`, `state/author-contacts/`
has a website, or Twenty is ready.

## What “hardened” means

| Lane | Success signal |
| --- | --- |
| **author_site** | On **missing-PDF** items whose creators match the pack, `run --dry-run` shows `author_site` in Would-hit; a live run may attach with stamp **`grey:author_site`** (not OA). |
| **authorwatch** | List members are **`ok`** (ORCID or OpenAlex id); first `run` without `--backfill-from` proposes **0**; `--backfill-from` proposes works not already in the library fingerprint; `apply` + `run` on `ocean/BBNJ-test` is boring and repeatable. |

## Phase 0 — Preconditions

1. Confirm the path: `paperful collections list` must show `ocean/BBNJ`.
2. `paperful doctor`. Refresh the mirror so `authors` reads `out/`.
3. Baseline **production** (read-only):

   ```sh
   paperful gaps -C ocean/BBNJ --list-missing
   paperful run -C ocean/BBNJ --dry-run --no-browser-agent
   ```

   Prefer `--format json` if you will diff later. Do **not** use this as the
   live fetch target for first experiments.
4. Optional knobs in `config.toml`: `[twenty].enabled`, `[searxng].base_url`,
   `[snowball].author_site_preflight` (off until Phase 2).

## Phase 1 — Author-site: corpus → pack → promote

Production harvest (already run once: `state/reports/ocean-bbnj-authors.json`):

```sh
paperful authors -C ocean/BBNJ
paperful authors -C ocean/BBNJ --apply
```

That writes `state/reports/ocean-bbnj-authors.json` and
`state/author-packs/ocean-bbnj.proposed.toml`. Corporate `name`-only creators
stay report-only.

**Human review (critical):** edit the proposed pack for the top **people** who
actually host greys/PDFs. Set `listing_url` or `base_host` (faculty /
institute publications page — not a journal landing, not ResearchGate). The
fetcher scrapes listing HTML for PDF links matched by DOI, title similarity,
or surname-in-URL (`paperful/sources/author_site.py`). Common surnames
(`wright|w`, `smith|s`, `wang|w`) need a listing URL, not fingerprint-only.

Promote, then `doctor` should show **author packs: N promoted**.

```sh
paperful snowball packs promote ocean-bbnj
paperful doctor
```

Dogfood the same loop on the test collection after Phase 0b:

```sh
paperful authors -C ocean/BBNJ-test
paperful authors -C ocean/BBNJ-test --apply
# edit listing_url on a few rows in state/author-packs/ocean-bbnj-test.proposed.toml
paperful snowball packs promote ocean-bbnj-test
paperful run -C ocean/BBNJ-test --dry-run --no-browser-agent --retry-failed
paperful run -C ocean/BBNJ-test --no-browser-agent --retry-failed   # small slice only
```

**Failure notes to keep:** `no pack match`, `no listing URL`,
`listing fetch failed`, `no title/DOI pdf on listing`. After wins:
`state/fetch-wins.jsonl`, attachment stamp `grey:author_site`.

Frequent people from the 2026-10-06 production report (not all are good
listing targets): Wright, Gjerde, Rochette, Dunn, Harden-Davies, Ardron,
Halpin, Currie, Vierros, Cremers, Freestone, Unger, Jaspars, Levin,
Mendenhall, Thiele, Jaeckel, Durussel, Tiller, Van Dover.

## Phase 0b — Create `ocean/BBNJ-test`

Do **not** copy the whole 1300-item tree. File a **small** membership subset
(missing-PDF + a few with PDFs from high-frequency people). `collections add`
files existing keys; it does not create the collection. Create the path first
(`ensure_collection_path` via ingest/apply, or a one-shot connect).

```sh
# keys file: one Zotero item key per line (from ocean/BBNJ)
paperful collections add -C ocean/BBNJ-test --keys-file state/bbnj-test-keys.txt --dry-run
paperful collections add -C ocean/BBNJ-test --keys-file state/bbnj-test-keys.txt --apply
```

If `resolve_collection` fails, create `ocean/BBNJ-test` in Zotero (or via
backend `ensure_collection_path`) then re-run add.

## Phase 2 — Optional boosters (one variable at a time)

| Booster | When | Command |
| --- | --- | --- |
| Twenty lookup/sync | CRM listings for ocean people | `paperful twenty lookup -C ocean/BBNJ --apply` then `twenty sync -C ocean/BBNJ --apply` |
| Write-back | After a real `author_site` attach | `run --twenty-writeback` (opt-in) |
| Snowball preflight | BBNJ snowball profile | `snowball … --author-site-preflight` (SearXNG caps) |

Keep production `-C ocean/BBNJ` for lookup/sync; keep **fetch experiments** on
`ocean/BBNJ-test`.

## Phase 3 — Authorwatch: `bbnj-test-voices`

Seed from people you already follow (ORCID preferred), not every co-author on
every BBNJ item.

```sh
paperful authorwatch save bbnj-test-voices
paperful authorwatch add bbnj-test-voices --orcid 0000-0002-XXXX-XXXX --name "Display Name"
paperful authorwatch resolve bbnj-test-voices
paperful authorwatch show bbnj-test-voices
paperful doctor   # must not amber “zero ok members” for this list
```

Cursor baseline (proposes 0, no library open):

```sh
paperful authorwatch run bbnj-test-voices
```

First useful poll (publication date, not OpenAlex index time):

```sh
paperful authorwatch run bbnj-test-voices --backfill-from 2024-01-01 --max-authors 10 --per-author-limit 20
paperful authorwatch briefing bbnj-test-voices
paperful authorwatch apply bbnj-test-voices -C ocean/BBNJ-test
paperful authorwatch apply bbnj-test-voices -C ocean/BBNJ-test --apply
paperful run -C ocean/BBNJ-test --dry-run --no-browser-agent
```

Cadence: weekly `authorwatch run` + review `state/authorwatch/bbnj-test-voices/inbox.jsonl`.
Paperful does not schedule.

If `authorwatch run` exits 2 with **OpenAlex daily budget is spent**, that is
the shared no-key pool (common on a VPN). Set `OPENALEX_API_KEY` and retry;
do not treat it as an empty frontier. Membership copies from `ocean/BBNJ`
were already tried in the production manifest: dogfood fetch needs
`--retry-failed` or the dry-run table stays empty. `run --dry-run` Would-hit
does not yet append `author_site` (the live pipeline does).

## Dogfood log (2026-10-06)

- Created **`ocean/BBNJ-test`** (Zotero key `44FTZZLW`); filed 20 keys from
  `ocean/BBNJ` (`state/bbnj-test-keys.txt`).
- Promoted pack `ocean-bbnj-test` with listings (IUCN Gjerde, IDDRI Rochette,
  Edinburgh Harden-Davies, glenwright.net Wright).
- `run --retry-failed --sources unpaywall,direct`: **2 attached** (`direct`,
  IDDRI PDFs). `author_site` ran on 10 leftovers: 8× `no title/DOI pdf on
  listing`, 1× `no pack match`, 1× `listing fetch failed`. Wright listing did
  not fire — Wright items in that 20 already had PDFs.
- `authorwatch` list `bbnj-test-voices`: 5 `ok` ORCIDs. An early poll hit a
  spent OpenAlex budget (traceback — now exit 2). Later
  `--backfill-from 2025-01-01 --max-authors 2` proposed **3**, `exists` **7**;
  `--apply` created 3 parents in `ocean/BBNJ-test`; one 2025 PDF attached via
  Unpaywall.

## Phase 4 — Engineering follow-ons (from real failures)

- HTML fixtures for 2–3 listing pages (win + miss) under `tests/fixtures/`.
- Golden pack row (`listing_url` + fingerprint) in tests.
- Tally `author_site` skip reasons from `attempts[]` / run JSON.
- Same person in pack + authorwatch: `exists` must skip duplicate creates.
- Do not add a nightly “ask everything” or scrape RG/LinkedIn.

## Risks (BBNJ-specific)

- **Org authorship** (FAO, ISA, UN, IUCN as `name`-only): no pack row, no
  `author_site`. Grey **playbooks** cover IGO PDFs; author-site is the long tail.
- **Common surnames:** hold or require ORCID / listing URL.
- **Treaty “canonical” BBNJ:** keep authorwatch creates on `ocean/BBNJ-test`.
- Saved profile `profiles/bbnj-journal.toml` uses `collections = ["ocean/BBNJ"]`.
