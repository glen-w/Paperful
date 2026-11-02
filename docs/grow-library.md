# Grow the library: topic search and people you follow

Add **metadata parents** for works you do not have yet. Filling PDFs is a
later step on [Wanted](first-fill.md). Snowball proposes; you keep, skip,
then apply.

## Outcome

You will have searched a topic (or followed an ORCID), reviewed the queue,
and created catalogue parents for the rows you kept — without fetching PDFs
in the same click.

## Starting point

Workbench at http://127.0.0.1:8765. A collection chip is helpful (new
parents can land there) but topic search itself does not require one.

The screenshots are the Discover page on a live `ocean/BBNJ` chip.

## What you’ll do

1. Open **Discover**.
2. Search a topic; review Keep / Skip.
3. **Preview apply**, then **Add selected**.
4. Optionally follow people by ORCID on the same page.
5. **Fill PDFs** jumps to Wanted for the new parents.

## Walkthrough

### Topic

1. Open **Discover**. **Topic** is a keyword search (`snowball search`,
   dry-run queue). Advanced can filter by OpenAlex study designs or trusted
   journal lists (`listed_in`: DOAJ, MEDLINE, …).

2. Type a query (for example `area based management`) and **Search**. You
   land on **Queue**, where per-row **Keep** / **Skip** marks the candidates.
   Nothing is written to Zotero yet. (**Explore**, the first tab, skips the
   keyword step: paste a DOI or title and **Open map**.)

![Discover: topic filled, ready to search or follow people](_static/workflows/discover.png)

3. Open **Queue**. The **Map** draws the candidates before you open a PDF:
   older and highly cited is likely foundational, recent and highly cited is
   influential now, recent with fewer citations may be emerging. Study-design
   badges (evidence synthesis, trials, …) sit on top of those roles. Click a
   paper to see why it is on the map, Keep or Skip it, or expand one hop
   (**References** / **Cited by**). The paginated candidate table is below
   the map.

![Discover Queue: the citation map of the last topic run, read-first list on the left](_static/workflows/discover-queue.png)

![Discover Queue: switch the map to Cited by, click a paper, read its card](_static/workflows/discover-map.gif)

4. **Preview apply**, then **Add selected**. That is `snowball apply`
   (metadata only). A stale preview refuses if the library changed.

5. Optional: back on **Topic**, **Briefing** / **Digest** write
   `briefing.md` / `digest.md` for the last run (shown on Queue; not
   auto-created). On **Queue**, **Keep an eye on this** saves a topic watch
   — only when a snowball **profile** is chosen, so save one on Advanced
   Topic first or the click returns an error banner. Saved watches and
   people lists appear under **Following**, each with a **Check again**
   button.

![Discover Following: saved topic watches and people lists with Check again](_static/workflows/discover-following.png)

6. **Fill PDFs** opens Wanted. Continue with [First fill](first-fill.md).

Advanced (toggle, cookie only) adds crawl kinds (hybrid / DOI / ORCID /
collection), hop knobs, a stopping rule (off unless you set it; **Next hop**
between hops), and profile save/run on Topic, plus a **Grow** tab with
**refs gap**, **ingest-dois**, **Authors frequency**, and **Packs promote**.
Those are the [research pack](research-pack.md) and [snowball](snowball.md)
surfaces, not the first click. The **Web** tab (SearXNG grey search, with
**Save watch** / **Run**) is the third default-nav way to grow; see
[Web grey search](search.md).

### People

Same page, **People** tab. This is `authorwatch` — people you already follow,
not a keyword hop.

1. Create a named list.
2. **Follow** with an ORCID (optional backfill date). Name-only rows stay
   unresolved until you confirm an iD.
3. **Run list** re-polls the list (**Check again** on the Following tab
   does the same). Inbox rows use the same Preview → apply pattern as topic.
4. **Get suggestions** ranks people already in the collection chip
   (`suggest -C`). Tick rows and **Accept selected** to put them on the list
   (optional **Initial seed from** date).

![Discover People: suggestions ticked, members already on the list](_static/workflows/discover-people.png)

Save a follows page from ResearchGate or LinkedIn and **Import**.
Details: [Author watch](authorwatch.md).

## What to notice

- Discover creates **parents**. Wanted fills **PDFs**. Do not conflate them
  with `run`.
- **Check again** re-runs the same search.
- `snowball watch` (saved keyword profile) is not `authorwatch` and not the
  PDF `inbox watch`.

## You should now have…

A reviewed queue, new metadata parents for the rows you applied, and a
clear next step on Wanted.

## CLI equivalent

```sh
docker compose run --rm paperful snowball search "area based management" --gate dry-run
# review state/snowball/<run-id>/
docker compose run --rm paperful snowball apply <run-id> --apply -C ocean/BBNJ
docker compose run --rm paperful authorwatch save ocean-people
docker compose run --rm paperful authorwatch add ocean-people --orcid 0000-0002-1825-0097
docker compose run --rm paperful authorwatch run ocean-people
```

## Next

- [First fill](first-fill.md) for the new parents
- [Research pack](research-pack.md) for works cited inside PDFs you already have
- [Snowball](snowball.md) for hop depth, gates, and watches
