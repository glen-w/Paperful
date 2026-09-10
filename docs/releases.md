# Releases and stability

**0.x** (including tagged `v0.2`) is a first usable release. Command flags,
config keys, and `paperful.run_report.v1` fields **may still move**.

**1.0** will lock:

- `paperful.run_report.v1` (additive keys only after that)
- attach behaviour (imported-file write-back, typed `attach_failed` reasons)

Until then, pin a git tag or commit if you script against JSON. See the
[changelog](https://github.com/glen-w/Paperful/blob/main/CHANGELOG.md) for
known limits.

## Ladder

```text
doctor → collections → run --dry-run → run → report / report --json
```

`--dry-run` lists each item and a **Would-hit** column (sources that routing
would try, in order). It does not download.

When Zotero is down, `collections`, `run`, and `attach` exit **2** and print
the same next-steps ladder (`paperful doctor`, enable local API, copy
`config.example.toml`).

## What 1.0 still owes operators

| Outcome | Status at 0.2 |
| --- | --- |
| Trust inside Zotero (attachment provenance stamp) | [Roadmap](ROADMAP.md#trust-10) |
| One-line end-of-run banner + write-API yes/no | Summary table ships; banner not locked |
| Locked report JSON schema | Schema named `paperful.run_report.v1`; not frozen |
