# Systematic review

Local protocol and screening under `state/sr/<slug>/`. Counts only. Paperful
does not replace Covidence, Rayyan, or ASReview, and it does not print a
recall percentage.

```bash
paperful sr init --slug bbnj --title "BBNJ EIA" --question "What is required?" \
  --reason off_topic --reason wrong_population
paperful sr screen --slug bbnj --identity 10.1000/example --decision exclude \
  --reason off_topic
paperful sr status --slug bbnj
paperful sr export --slug bbnj --format csv
paperful sr import --slug bbnj included.csv          # dry-run
paperful sr import --slug bbnj included.csv --apply  # ledger only
```

`--search-run` and `--snowball-run` on `init` point at packs already on disk.
They are not a new crawl.

An `exclude` reason must be one of the protocol's `--reason` values. `maybe`
does not need a reason. `status` prints how many excludes used each reason.

`status` writes `prisma.json` and `prisma.svg` beside the protocol. The SVG
is those integers in fixed boxes.

`import --apply --collection` can create metadata parents for included rows
through the same path as search apply. Screening itself does not attach PDFs.
Leave `--collection` off to keep the import on the ledger.

Advanced `/review` records a decision and can preview an apply. It is not in
the nav. There is no scheduler.
