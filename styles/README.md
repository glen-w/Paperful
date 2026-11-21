# Vale house styles

Example Vale packs for optional `paperful peer-review --vale`. They live under
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

Then `[peer_review].vale = true` or `paperful peer-review --vale`. See
[peer_review](../docs/peer-review.md#example-vale-styles).

Other directories under `styles/` (personal or venue tints) stay local and
are gitignored. Keep them next to the examples so `StylesPath = styles` still
finds them; point `[peer_review].vale_config` at a sibling ini that names that
pack only.
