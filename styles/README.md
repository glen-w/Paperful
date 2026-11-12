# Vale house styles

Example Vale packs for optional `paperful critique --vale`. They live under
`styles/` so a repo-root `.vale.ini` can set `StylesPath = styles`. None of
them is an official journal package.

| Pack | Venue | Citation in the text |
| --- | --- | --- |
| [`JMLC`](JMLC/) | Journal of Money Laundering Control (Emerald) | Harvard author–year |
| [`JCP`](JCP/) | Journal of Cleaner Production (Elsevier) | Author–year |
| [`MarinePolicy`](MarinePolicy/) | Marine Policy (Elsevier) | Numbered `[1]` |

Do not enable `JCP` and `MarinePolicy` together (citation styles conflict).

Copy one example ini to the paperful config directory:

```bash
cp styles/JMLC/vale.ini.example .vale.ini
# or: cp styles/JCP/vale.ini.example .vale.ini
# or: cp styles/MarinePolicy/vale.ini.example .vale.ini
```

Then `[critique].vale = true` or `paperful critique --vale`. See
[critique](../docs/critique.md#example-vale-styles).

Other directories under `styles/` (personal or venue tints) stay local and
are gitignored. Keep them next to the examples so `StylesPath = styles` still
finds them; point `[critique].vale_config` at a sibling ini that names that
pack only.
