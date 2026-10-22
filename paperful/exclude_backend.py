"""Shared [[exclude]] checks for LibraryBackend implementations."""

from __future__ import annotations

from .exclude import ExcludeDenied, ExcludeGuard


class ExcludeMixin:
    """Mixin for backends that expose ``cfg`` and ``collections()``.

    Subclasses MUST implement:
      - ``self.cfg`` with ``exclude_rules``
      - ``collections() -> dict[str, Collection]``
      - ``_item_collection_keys(item_key: str) -> list[str]``
    """

    def _exclude_guard(self) -> ExcludeGuard:
        rules = getattr(self.cfg, "exclude_rules", ()) or ()
        if not rules:
            return ExcludeGuard.empty()
        return ExcludeGuard(rules, self.collections())

    def _deny_excluded(self, exc: ExcludeDenied) -> None:
        from .library import LibraryError  # late import: avoid cycles

        raise LibraryError(exc.message) from exc

    def _check_item_op(self, op: str, item_key: str) -> None:
        if not (getattr(self.cfg, "exclude_rules", ()) or ()):
            return
        try:
            self._exclude_guard().check_item(op, self._item_collection_keys(item_key))
        except ExcludeDenied as exc:
            self._deny_excluded(exc)

    def _check_collection_op(self, op: str, collection_key: str) -> None:
        if not (getattr(self.cfg, "exclude_rules", ()) or ()):
            return
        try:
            self._exclude_guard().check_collection(op, collection_key)
        except ExcludeDenied as exc:
            self._deny_excluded(exc)

    def _check_path_op(self, op: str, path: str) -> None:
        if not (getattr(self.cfg, "exclude_rules", ()) or ()):
            return
        try:
            self._exclude_guard().check_path(op, path)
        except ExcludeDenied as exc:
            self._deny_excluded(exc)
