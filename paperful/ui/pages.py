"""Row builders for workbench pages (no HTML).

Desk modules: ``wanted_rows``, ``discover_rows``, ``ask_rows``. Shared helpers
live in ``page_common``. This module re-exports the public names so existing
imports keep working.
"""

from __future__ import annotations

from .ask_rows import (
    ASK_ERROR_MESSAGES,
    SUMMARIZE_ORDERS,
    ask_mode_options,
    ask_page_flags,
    briefs_page_flags,
    briefs_synth_form,
    critique_pack_markdown,
    focus_options,
    last_ask_result,
    list_answered_packs,
    list_ask_packs,
    list_html_stems,
    list_recent_critiques,
    list_recent_summaries,
    list_threads,
    summary_meta,
    thread_for_display,
)
from .discover_rows import (
    DISCOVER_TABS,
    authorwatch_inbox_rows,
    authorwatch_lists,
    authorwatch_people_rows,
    authorwatch_suggestion_rows,
    candidate_title_doi,
    following_lists,
    list_snowball_profiles,
    newest_search_run,
    newest_snowball_queue,
    resolve_discover_tab,
    snowball_deferred_run_id,
    snowball_stop_view,
)
from .page_common import (
    DEST_OPTIONS,
    MIRROR_VERBS,
    REPAIR_VERBS,
    SYNTHESIZE_SKIP_MESSAGES,
    coerce_library_per_page,
    command_by_id,
    dest_for_form,
    dest_options,
    job_view,
    last_job_result,
    library_has_attached_pdf,
    library_item_rows,
    library_items_page,
    library_page_from_request,
    library_page_size_options,
    library_per_page_from_request,
    nest_collection_rows,
    paginate_rows,
    pagination_meta,
    queue_fingerprint,
    repair_queues,
    safe_child,
    scope_fingerprint,
)
from .wanted_rows import (
    WANTED_FILTER_LABELS,
    WANTED_FILTERS,
    WANTED_ORDER_LABELS,
    WANTED_ORDERS,
    filter_wanted_rows,
    resolve_wanted_tab,
    sort_wanted_rows,
    wanted_filter_from_request,
    wanted_items_page,
    wanted_order_from_request,
    wanted_query_from_request,
    wanted_rows,
)

__all__ = [name for name in dir() if not name.startswith("_")]
