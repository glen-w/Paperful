"""Edit a few scalar keys in ``config.toml`` without disturbing the rest.

The Settings page only touches a handful of root and ``[ui]`` keys. Rather
than round-tripping the whole file through a TOML writer (which would drop
comments), this patches lines in place but with three guarantees the old
regex helper lacked:

* values are written as valid TOML basic strings (quotes and backslashes
  escaped), so a path with a ``"`` cannot corrupt the file;
* a root key is only matched in the root table (before the first ``[``), so
  ``email`` never lands inside ``[twenty]``;
* the result parses, and is written atomically.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..fsio import atomic_write_text

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - py310
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigPatchError(ValueError):
    """The patch would leave an unparseable or unsafe config."""


def toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    # TOML basic strings share JSON's escape rules for the characters that
    # matter here (quote, backslash, control characters).
    return json.dumps(str(value), ensure_ascii=False)


def _split_root(text: str) -> tuple[str, str]:
    """Return (root table text, everything from the first table header)."""
    match = re.search(r"^\s*\[", text, re.MULTILINE)
    if not match:
        return text, ""
    return text[: match.start()], text[match.start() :]


def _assign_in_block(block: str, key: str, literal: str) -> str:
    line = f"{key} = {literal}"
    key_re = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", re.MULTILINE)
    if key_re.search(block):
        return key_re.sub(lambda _m: line, block, count=1)
    if block and not block.endswith("\n"):
        block += "\n"
    return block + line + "\n"


def patch_assignment(text: str, section: str, key: str, value: object) -> str:
    """Set ``section.key = value`` (``section=""`` for the root table)."""
    literal = toml_literal(value)
    if not section:
        root, rest = _split_root(text)
        root = _assign_in_block(root, key, literal)
        if rest and not root.endswith("\n\n"):
            root = root.rstrip("\n") + "\n\n"
        return root + rest
    header = re.compile(rf"^\[{re.escape(section)}\][ \t]*$", re.MULTILINE)
    found = header.search(text)
    if not found:
        return text.rstrip("\n") + f"\n\n[{section}]\n{key} = {literal}\n"
    start = found.end()
    nxt = re.search(r"^\s*\[", text[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(text)
    block = _assign_in_block(text[start:end], key, literal)
    if not block.startswith("\n"):
        block = "\n" + block.lstrip("\n")
    return text[:start] + block + text[end:]


def apply_patches(path: Path, patches: dict[tuple[str, str], object]) -> None:
    """Apply ``{(section, key): value}`` to ``path`` and write atomically.

    Raises ``ConfigPatchError`` if the file is missing or the patched text
    would not parse; the original file is left untouched in that case.
    """
    if not path.is_file():
        raise ConfigPatchError(f"{path} does not exist")
    text = path.read_text(encoding="utf-8")
    for (section, key), value in patches.items():
        text = patch_assignment(text, section, key, value)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigPatchError(f"refusing to write an invalid config: {exc}") from exc
    atomic_write_text(path, text)
