# Screen for problematic papers (PPS-based)

`paperful screen` flags items in your library using public signals aligned with the [Problematic Paper Screener](https://www.irit.fr/~Guillaume.Cabanac/problematic-paper-screener) (PPS). It does **not** scrape the PPS “all papers” APEX list and does **not** decide misconduct — it surfaces evidence for you to review.

## What it checks

| Signal | Source |
| --- | --- |
| Retraction / withdrawal / expression of concern | Crossref `update-to` and OpenAlex `is_retracted` |
| PubPeer comments | Optional `POST` to PubPeer API (`[screen].pubpeer` + `PUBPEER_DEVKEY`) |
| Tortured phrases, SCIgen, Mathgen, suspect templates | Local PDF/text vs fingerprint lists (cached under `state/pps/fingerprints/`, optional `[screen].fingerprint_dir`, or fetched from PPS [CSV dumps](https://dbrech.irit.fr/pls/apex/f?p=9999:5)) |

Tortured-phrase hits follow PPS practice: **5+** fingerprint matches, or **one** bundled “obvious” phrase (for example `sign to clamor`). Other families flag on any match.

## CLI

```bash
uv run paperful screen -C "My Collection"          # report only
uv run paperful screen -C "My Collection" --strict
uv run paperful screen -C "My Collection" --apply  # tag + child note
uv run paperful screen --refresh                   # bypass status cache; re-fetch CSVs
```

Reports land in `state/runs/<stamp>-screen.json`. Status lookups are cached under `state/pps/status/`; fingerprint CSVs under `state/pps/fingerprints/`.

Matching is **fully local** once lists are on disk. Run `paperful screen --refresh` (or any online screen/critique that fetches CSVs) to populate the cache; copy the four families from PPS into `[screen].fingerprint_dir` as `tortured.csv`, `scigen.csv`, `mathgen.csv`, and `suspect.csv` if you want an air-gapped source of truth. Offline critique and screen use cache or `fingerprint_dir` and do not call IRIT.

## Write-back (`--apply`)

- Parent tag prefix `paperful pps:` (replaced on re-run)
- One child note tagged `[screen].tag` (default `paperful-pps`) with links and matched phrases

Bibliographic fields are never changed.

`paperful critique` reuses the same Crossref / OpenAlex status cache for
**cited** works in a manuscript bibliography (`cited_retracted`,
`cited_withdrawn`, `cited_expression_of_concern`). See [critique](critique.md).

## Config

See `[screen]` in [config.md](config.md) and `config.example.toml`.

## Attribution

Method reference: Cabanac, Labbé, & Magazinov (2022), [arXiv:2210.04895](https://doi.org/10.48550/arXiv.2210.04895).
