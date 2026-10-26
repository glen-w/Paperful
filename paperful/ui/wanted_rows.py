"""Wanted desk row builders (no HTML)."""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..miss_surface import (
    honesty_row_for_item,
    miss_surface_plain,
    project_miss_surface,
)
from ..store import Manifest, STATUS_ATTACHED, STATUS_OK
from .page_common import _item_row_base, paginate_rows
from .verify import file_verification, reason_plain, stamp_for_state, verification_plain

_WANTED_TABS = ("missing", "held", "have")

WANTED_ORDERS = ("title", "year_new", "year_old")

WANTED_FILTERS = ("all", "summary", "no_summary")

WANTED_ORDER_LABELS = (
    ("title", "Title"),
    ("year_new", "Year (newest)"),
    ("year_old", "Year (oldest)"),
)

WANTED_FILTER_LABELS = (
    ("all", "All"),
    ("summary", "With summary"),
    ("no_summary", "Without summary"),
)


def wanted_rows(
    cfg: Config,
    items: list[Any],
    manifest: Manifest,
) -> dict[str, Any]:
    have: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for item in items:
        rec = manifest.records.get(item.key)
        base = _item_row_base(cfg, item)
        if item.has_pdf or (
            rec is not None and rec.status in {STATUS_OK, STATUS_ATTACHED}
        ):
            ver = file_verification(rec, item_doi=item.doi)
            row = {
                **base,
                **ver,
                "verify_plain": verification_plain(ver["state"]),
                "verify_tip": reason_plain(ver.get("reason") or ""),
                "ticked": ver["state"] == "doi_match",
                "stamp": stamp_for_state(ver["state"]),
            }
            state = ver["state"]
            if state == "doi_match":
                have.append(row)
            elif state == "missing":
                missing.append(
                    {
                        **row,
                        "miss_surface": "missing",
                        "miss_plain": row["verify_plain"],
                        "miss_detail": row["verify_tip"],
                    }
                )
            else:
                held.append(row)
            continue
        honesty = honesty_row_for_item(cfg, item, rec)
        code = str(honesty.get("miss_surface") or "")
        if code == "import_ok":
            continue
        plain = str(honesty.get("miss_plain") or "")
        if not plain and not code:
            code = project_miss_surface(
                doi=item.doi,
                arxiv_id=getattr(item, "arxiv_id", None),
                url=getattr(item, "url", None),
                has_pdf=False,
                status=str(getattr(rec, "status", "") or "") if rec else "",
                attempts=list(getattr(rec, "attempts", None) or []) if rec else [],
                source=getattr(rec, "source", None) if rec else None,
            )
            if code == "import_ok":
                continue
            plain = miss_surface_plain(code) if code else miss_surface_plain("not_fetched")
            code = code or "not_fetched"
        if not plain:
            continue
        missing.append(
            {
                **base,
                "miss_surface": code,
                "miss_plain": plain,
                "miss_detail": str(honesty.get("miss_detail") or ""),
            }
        )

    item_keys = {it.key for it in items}
    pending_keys = {
        r.itemKey for r in manifest.pending_attach() if r.itemKey in item_keys
    }
    for row in have + held:
        # Main Attach skips DOI mismatches even when the reason field is empty.
        row["attachable"] = (
            row.get("key") in pending_keys and row.get("state") != "doi_mismatch"
        )
    for row in missing:
        row["attachable"] = False
    attach_pending = sum(1 for r in have + held if r.get("attachable"))

    return {
        "have": have,
        "held": held,
        "missing": missing,
        "counts": {
            "have": len(have),
            "held": len(held),
            "missing": len(missing),
            "attach": attach_pending,
            "found": sum(1 for r in have + held if r.get("stamp") == "found"),
            "check": sum(1 for r in have + held if r.get("stamp") == "check"),
        },
    }


def resolve_wanted_tab(tab: str | None, counts: dict[str, int]) -> str:
    """Pick a Wanted tab; default to the first non-empty bucket."""
    if tab in _WANTED_TABS:
        return tab
    for name in _WANTED_TABS:
        if counts.get(name, 0) > 0:
            return name
    return "missing"


def wanted_order_from_request(request: Any) -> str:
    raw = str(request.query_params.get("order") or "").strip().lower()
    return raw if raw in WANTED_ORDERS else "title"


def wanted_filter_from_request(request: Any) -> str:
    raw = str(request.query_params.get("filter") or "").strip().lower()
    return raw if raw in WANTED_FILTERS else "all"


def wanted_query_from_request(request: Any) -> str:
    return str(request.query_params.get("q") or "").strip()


def filter_wanted_rows(
    rows: list[dict[str, Any]], *, filt: str, query: str
) -> list[dict[str, Any]]:
    out = rows
    needle = (query or "").strip().lower()
    if needle:
        out = [
            row
            for row in out
            if needle in str(row.get("title") or "").lower()
            or needle in str(row.get("key") or "").lower()
            or needle in str(row.get("doi") or "").lower()
        ]
    if filt == "summary":
        out = [row for row in out if row.get("has_summary")]
    elif filt == "no_summary":
        out = [row for row in out if not row.get("has_summary")]
    return out


def sort_wanted_rows(rows: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    if order == "year_new":
        return sorted(
            rows,
            key=lambda row: (
                -(int(row["year"]) if row.get("year") is not None else -1),
                str(row.get("title") or "").lower(),
                str(row.get("key") or ""),
            ),
        )
    if order == "year_old":
        return sorted(
            rows,
            key=lambda row: (
                int(row["year"]) if row.get("year") is not None else 9999,
                str(row.get("title") or "").lower(),
                str(row.get("key") or ""),
            ),
        )
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("title") or "").lower(),
            str(row.get("key") or ""),
        ),
    )


def wanted_items_page(
    rows: list[dict[str, Any]],
    *,
    page: int,
    per_page: int,
    order: str = "title",
    filt: str = "all",
    query: str = "",
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Filter, sort, and paginate one Wanted tab's rows."""
    filtered = filter_wanted_rows(rows, filt=filt, query=query)
    ordered = sort_wanted_rows(filtered, order)
    return paginate_rows(ordered, page=page, per_page=per_page)
