# Vale style: PaperfulAi

Optional house-style rules for **promotional and chatbot leftovers** in academic
prose. They are hygiene, not an authorship detector and not a Turnitin bypass.

## Quick start

```bash
cp styles/PaperfulAi/vale.ini.example .vale.ini
```

```toml
[peer_review]
vale = true
vale_config = ".vale.ini"
```

```bash
uv run paperful peer-review --file manuscript.docx --vale
```

Peer-review also runs a built-in discourse checker (`[peer_review].discourse`,
default on) when Vale is off. Vale here is an extra swap list you can merge
with JMLC / JCP / MarinePolicy.
