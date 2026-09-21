# Releases and stability

**0.x** (including tagged `v0.5`) is a first usable release. Command flags,
config keys, and `paperful.run_report.v1` fields **may still move**.

**1.0** will lock:

- `paperful.run_report.v1` (additive keys only after that)
- `paperful.item.v1` and `snapshot` / `restore` behaviour (additive keys only after that)
- attach behaviour (imported-file write-back, typed `attach_failed` reasons)

A second manager is not owed as a finished feature. Mendeley and EndNote
adapters are in the tree and **seeking testers**; Zotero is the well-tested
path. Until 1.0, pin a git tag or commit if you script against JSON. See the
[changelog](https://github.com/glen-w/Paperful/blob/main/CHANGELOG.md) for
known limits. See [Why paperful](why.md).

## Ladder

```text
doctor → collections → run --dry-run → run → report / report --json
```

`--dry-run` lists each item and a **Would-hit** column (sources that routing
would try, in order). It does not download. Narrow with `--collection` /
`--library`, plus optional `--year-from` / `--year-to` and `--type` / `-T`
([Commands — Scope filters](commands.md#scope-filters)).

When Zotero is down, `collections`, `run`, `attach`, `lint`, `fix-metadata`,
`dedupe`, `gaps`, `recover`, `summarize`, and `synthesize` exit **2** and print the same
next-steps ladder (`paperful doctor`, enable local API, copy
`config.example.toml`).

## Optional LLM at 0.5

Off by default and additive: with `[llm].enabled = false` nothing in the PDF
loop changes. Known limits: `recover` needs Python 3.11+ and a 14B-class
local model to be useful; the Docker image does not include the LLM extras;
identity/title verbs need a text-layer PDF (no OCR). `summarize` and
`synthesize` default to writing both a disk file and a Zotero note
(`--to disk` keeps the library tree clean). Config keys under `[llm]`,
`[browser_agent]`, `[summarize]`, `[synthesize]`, `[lint]`, `[fix_metadata]` may still move
before 1.0. See [LLM](llm.md).

## What 1.0 still owes operators

| Outcome | Status at 0.5 |
| --- | --- |
| Trust inside Zotero (attachment provenance stamp) | [Roadmap](ROADMAP.md#trust-10) |
| One-line end-of-run banner + write-API yes/no | Summary table ships; banner not locked |
| Locked report JSON schema | Schema named `paperful.run_report.v1`; not frozen |
| Locked item record + snapshot/restore | `paperful.item.v1` named; 0.x may add keys |
| Mendeley and EndNote adapters | In the tree. Seeking testers. Zotero is the well-tested path |
