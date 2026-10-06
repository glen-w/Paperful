"""One-line next steps for doctor rows in the workbench."""

from __future__ import annotations

_STEPS: dict[str, str] = {
    "zotero_down": "Start Zotero on this machine, then refresh System.",
    "zotero_api_off": "In Zotero: Settings → Advanced → Enable HTTP server and allow other applications.",
    "zotero_bad_host": "Set zotero_host in config.toml to match Zotero’s allowed host.",
    "zotero_no_write": "Enable write access in Zotero’s local API settings for attach and apply.",
    "unpaywall_email": "Add your email under [unpaywall] in config.toml (Settings).",
}


def next_step(code: str, detail: str) -> str:
    if code in _STEPS:
        return _STEPS[code]
    return detail or "See paperful doctor on the command line."
