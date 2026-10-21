"""Collection exclude / protect rules for library writes.

``[[exclude]]`` in config.toml marks collection subtrees that paperful must
not mutate (or may only add to). Enforcement lives on LibraryBackend writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .zot import Collection, resolve_collection_in, subtree_keys_in

MODES = frozenset({"full", "add_only", "custom"})
OPS = frozenset(
    {
        "create",
        "add",
        "ensure_path",
        "update",
        "notes",
        "tags",
        "attach",
        "trash",
        "collection_notes",
        "merge",
    }
)

# allow_* field on ExcludeRule for each op
_OP_ALLOW = {
    "create": "allow_create",
    "add": "allow_add",
    "ensure_path": "allow_ensure_path",
    "update": "allow_update",
    "notes": "allow_notes",
    "tags": "allow_tags",
    "attach": "allow_attach",
    "trash": "allow_trash",
    "collection_notes": "allow_collection_notes",
    "merge": "allow_merge",
}


@dataclass(frozen=True)
class ExcludeRule:
    """One protect rule after preset expansion."""

    path: str = ""
    key: str = ""
    mode: str = "full"
    allow_create: bool = False
    allow_add: bool = False
    allow_ensure_path: bool = False
    allow_update: bool = False
    allow_notes: bool = False
    allow_tags: bool = False
    allow_attach: bool = False
    allow_trash: bool = False
    allow_collection_notes: bool = False
    allow_merge: bool = False
    protect_items: bool = True
    skip_library_scope: bool = False

    def label(self) -> str:
        if self.path:
            return self.path
        if self.key:
            return f"key:{self.key}"
        return "(unnamed)"

    def allows(self, op: str) -> bool:
        field = _OP_ALLOW.get(op)
        if field is None:
            return True
        return bool(getattr(self, field))


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _preset_allows(mode: str) -> dict[str, bool]:
    """Default allow_* flags for a mode (before explicit overrides)."""
    deny = {name: False for name in _OP_ALLOW.values()}
    if mode == "add_only":
        deny["allow_create"] = True
        deny["allow_add"] = True
        deny["allow_ensure_path"] = True
    return deny


def parse_exclude_rule(row: dict[str, Any], *, index: int = 0) -> ExcludeRule:
    """Parse one ``[[exclude]]`` table into an expanded rule."""
    path = str(row.get("path") or "").strip().strip("/")
    key = str(row.get("key") or "").strip()
    if not path and not key:
        raise ValueError(
            f"exclude[{index}] needs path or key (got neither)"
        )
    mode = str(row.get("mode") or "full").strip().lower() or "full"
    if mode not in MODES:
        raise ValueError(
            f"exclude[{index}] mode must be one of {sorted(MODES)}, got {mode!r}"
        )
    allows = _preset_allows(mode)
    for field in list(allows):
        if field in row:
            allows[field] = _as_bool(row[field], allows[field])
        # also accept short names without allow_ prefix in TOML? stick to allow_*
    protect_default = True
    skip_default = False
    return ExcludeRule(
        path=path,
        key=key,
        mode=mode,
        protect_items=_as_bool(row.get("protect_items"), protect_default),
        skip_library_scope=_as_bool(row.get("skip_library_scope"), skip_default),
        **allows,
    )


def parse_exclude_rules(raw: Any) -> tuple[ExcludeRule, ...]:
    """Parse top-level ``exclude`` (array of tables) from config."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(
            f"exclude must be an array of tables ([[exclude]]), got {type(raw).__name__}"
        )
    out: list[ExcludeRule] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(
                f"exclude[{i}] must be a table, got {type(row).__name__}"
            )
        out.append(parse_exclude_rule(row, index=i))
    return tuple(out)


def _squash_path(s: str) -> str:
    text = s.strip().strip("/").lower()
    parts = [p for p in text.replace("\\", "/").split("/") if p]
    return "/".join(parts)


def path_under(candidate: str, root: str) -> bool:
    """True when ``candidate`` is ``root`` or a descendant path."""
    c = _squash_path(candidate)
    r = _squash_path(root)
    if not r:
        return False
    return c == r or c.startswith(r + "/")


class ExcludeDenied(Exception):
    """Raised by ExcludeGuard; backends wrap as LibraryError."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class _BoundRule:
    rule: ExcludeRule
    keys: frozenset[str]
    resolved_path: str


class ExcludeGuard:
    """Resolve rules against a live collection tree and check operations."""

    def __init__(
        self,
        rules: tuple[ExcludeRule, ...] | list[ExcludeRule],
        cols: dict[str, Collection],
    ):
        self.rules = tuple(rules)
        self.cols = cols
        self._bound: list[_BoundRule] = []
        self.unmatched: list[ExcludeRule] = []
        for rule in self.rules:
            bound, resolved = self._bind(rule)
            if bound is None:
                self.unmatched.append(rule)
            else:
                self._bound.append(bound)
                if not resolved:
                    self.unmatched.append(rule)

    @classmethod
    def empty(cls) -> ExcludeGuard:
        return cls((), {})

    def _bind(self, rule: ExcludeRule) -> tuple[_BoundRule | None, bool]:
        """Return (bound rule or None, True when path/key resolved in the tree)."""
        root: Collection | None = None
        if rule.key and rule.key in self.cols:
            root = self.cols[rule.key]
        elif rule.path:
            try:
                root = resolve_collection_in(self.cols, rule.path)
            except LookupError:
                root = None
        if root is None:
            # Path-only rule may still match not-yet-created descendants via
            # prefix; keep an empty key set and use path matching.
            if rule.path:
                return _BoundRule(rule, frozenset(), rule.path), False
            return None, False
        keys = frozenset(subtree_keys_in(self.cols, root))
        return _BoundRule(rule, keys, root.path or rule.path), True

    def _matching(self, collection_key: str) -> list[_BoundRule]:
        return [b for b in self._bound if collection_key and collection_key in b.keys]

    def _matching_path(self, path: str) -> list[_BoundRule]:
        out: list[_BoundRule] = []
        for b in self._bound:
            root = b.rule.path or b.resolved_path
            if root and path_under(path, root):
                out.append(b)
        return out

    def check_collection(self, op: str, collection_key: str) -> None:
        """Deny when any matching rule forbids ``op`` on this collection key."""
        if op not in OPS or not collection_key:
            return
        for b in self._matching(collection_key):
            if not b.rule.allows(op):
                raise ExcludeDenied(
                    f"excluded: cannot {op.replace('_', ' ')} in "
                    f"{b.rule.label()!r} (mode={b.rule.mode})"
                )

    def check_path(self, op: str, path: str) -> None:
        """Deny when ``path`` sits under a rule that forbids ``op`` (even if missing)."""
        if op not in OPS or not path:
            return
        for b in self._matching_path(path):
            if not b.rule.allows(op):
                raise ExcludeDenied(
                    f"excluded: cannot {op.replace('_', ' ')} under "
                    f"{b.rule.label()!r} (mode={b.rule.mode})"
                )

    def check_item(self, op: str, collection_keys: Iterable[str]) -> None:
        """Deny item mutations when protect_items and any membership matches."""
        if op not in OPS:
            return
        keys = [str(k) for k in collection_keys if k]
        if not keys:
            return
        for key in keys:
            for b in self._matching(key):
                if not b.rule.protect_items:
                    continue
                if not b.rule.allows(op):
                    raise ExcludeDenied(
                        f"excluded: cannot {op.replace('_', ' ')} items in "
                        f"{b.rule.label()!r} (mode={b.rule.mode})"
                    )

    def library_skip_keys(self) -> frozenset[str]:
        """Collection keys omitted from unscoped / --library item lists."""
        out: set[str] = set()
        for b in self._bound:
            if b.rule.skip_library_scope:
                out.update(b.keys)
        return frozenset(out)

    def item_paths_fully_skipped(self, collection_paths: Iterable[str]) -> bool:
        """True when every non-empty path maps into skip_library_scope keys."""
        skip = self.library_skip_keys()
        if not skip:
            return False
        keys: list[str] = []
        for path in collection_paths:
            text = str(path or "").strip()
            if not text or text.startswith("_"):
                continue
            for c in self.cols.values():
                if c.path == text or c.raw_path == text:
                    keys.append(c.key)
                    break
        if not keys:
            return False
        return set(keys) <= skip


def filter_library_scope_items(
    items: list[Any],
    guard: ExcludeGuard,
) -> list[Any]:
    """Drop items whose membership is entirely under skip_library_scope rules."""
    if not guard.library_skip_keys():
        return items
    out = []
    for item in items:
        paths = getattr(item, "collection_paths", None) or []
        if guard.item_paths_fully_skipped(paths):
            continue
        out.append(item)
    return out
