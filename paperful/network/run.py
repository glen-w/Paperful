"""Orchestrate an ORCID ego network run into ``state/network/<run-id>/``."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..snowball.authors import AuthorRecord, name_fingerprint
from ..snowball.local_openalex import store_from_config
from ..snowball.openalex import OpenAlexClient, normalize_orcid, short_id
from .attributes import apply_attributes, seed_attributes, write_attributes_csv
from .build import NETWORK_SELECT, build_ego_graph
from .metrics import compute_graph_metrics, networkx_available
from .phases import Phase, load_phases, slice_graph
from .store import (
    SCHEMA,
    NetworkError,
    new_run_id,
    run_dir,
    write_run,
)


def openalex_client(cfg: Config, client: Any = None) -> OpenAlexClient:
    if client is not None:
        return client
    return OpenAlexClient(
        email=cfg.email,
        store=store_from_config(cfg),
        store_fail_limit=int(getattr(cfg, "openalex_store_fail_limit", 3) or 3),
    )


def run_orcid(
    cfg: Config,
    orcid: str,
    *,
    phases: str = "bbnj",
    partition: str = "none",
    max_works: int = 500,
    max_alters: int = 150,
    client: Any = None,
    figures: bool = False,
    run_id: str | None = None,
    dest: Path | None = None,
) -> dict[str, Any]:
    cleaned = normalize_orcid(orcid)
    if not cleaned:
        raise NetworkError("Pass a 16-digit ORCID with hyphens.")
    phase_list = load_phases(phases)
    oa = openalex_client(cfg, client)
    author = oa.author_by_orcid(cleaned) or {}
    ego = _ego_from_author(author, cleaned)
    works = oa.works_by_author(
        orcid=cleaned,
        openalex=ego.openalex,
        limit=max(1, int(max_works or 500)),
        select=NETWORK_SELECT,
    )
    graph = build_ego_graph(
        works,
        orcid=cleaned,
        ego=ego,
        max_alters=max(0, int(max_alters or 0)),
    )
    attrs = seed_attributes(graph)
    graph = apply_attributes(graph, attrs)

    part = (partition or "none").strip().lower()
    if part in {"", "off"}:
        part = "none"
    if part not in {"none", "region", "discipline", "sector"}:
        raise NetworkError("Partition must be region, discipline, sector, or none.")
    if part != "none" and not networkx_available():
        from .metrics import NETWORKX_HINT

        raise NetworkError(
            "Brokerage roles need NetworkX. " + NETWORKX_HINT,
            code=2,
        )

    advanced = networkx_available()
    full_metrics = compute_graph_metrics(graph, partition=part, advanced=advanced)
    phase_payloads: dict[str, dict[str, Any]] = {}
    ego_series: list[dict[str, Any]] = []
    for phase in phase_list:
        sliced = slice_graph(graph, phase)
        sliced = apply_attributes(sliced, attrs)
        metrics = compute_graph_metrics(sliced, partition=part, advanced=advanced)
        phase_payloads[phase.id] = {
            "schema": SCHEMA,
            "graph": sliced,
            "metrics": metrics,
        }
        ego_series.append(
            {
                "phase": phase.id,
                "label": phase.label,
                **(metrics.get("ego") or {}),
                "nodes": metrics.get("nodes"),
                "edges": metrics.get("edges"),
            }
        )

    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rid = (run_id or "").strip() or new_run_id(cleaned)
    out = dest if dest is not None else run_dir(cfg, rid)
    meta = {
        "schema": SCHEMA,
        "run_id": rid,
        "orcid": cleaned,
        "openalex": ego.openalex,
        "display_name": ego.display_name or str((graph.get("ego") or {}).get("display_name") or ""),
        "built_at": stamp,
        "phases": [p.to_dict() for p in phase_list],
        "partition": part,
        "max_works": int(max_works or 500),
        "max_alters": int(max_alters or 0),
        "works": len(works),
        "nodes": len(graph.get("nodes") or []),
        "edges": len(graph.get("edges") or []),
        "advanced": bool(full_metrics.get("advanced")),
        "advanced_error": str(full_metrics.get("advanced_error") or ""),
    }
    bundle_metrics = dict(full_metrics)
    bundle_metrics["by_phase"] = ego_series
    write_run(
        out,
        meta=meta,
        graph=graph,
        phases=phase_payloads,
        metrics=bundle_metrics,
        attributes=attrs,
    )
    figure_paths: list[str] = []
    if figures:
        from .figures import write_phase_figures

        written = write_phase_figures(
            out / "figures",
            {slug: payload["graph"] for slug, payload in phase_payloads.items()},
        )
        figure_paths = [str(p) for p in written]
        meta["figures"] = figure_paths
        (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return {
        "run_id": rid,
        "path": str(out),
        "meta": meta,
        "graph": graph,
        "metrics": bundle_metrics,
        "phases": phase_payloads,
        "attributes": attrs,
        "figures": figure_paths,
    }


def refresh_metrics(
    cfg: Config,
    run_id: str,
    *,
    partition: str | None = None,
) -> dict[str, Any]:
    """Recompute metrics after an attributes CSV edit."""
    from .attributes import read_attributes_csv
    from .store import load_run

    bundle = load_run(cfg, run_id)
    dest = Path(bundle["path"])
    attrs = read_attributes_csv(dest / "attributes.csv") or bundle.get("attributes") or []
    graph = apply_attributes(bundle["graph"], attrs)
    part = (partition or bundle["meta"].get("partition") or "none").strip().lower()
    advanced = networkx_available()
    full_metrics = compute_graph_metrics(graph, partition=part, advanced=advanced)
    phase_payloads: dict[str, dict[str, Any]] = {}
    ego_series: list[dict[str, Any]] = []
    for raw in bundle["meta"].get("phases") or []:
        phase = Phase(
            id=str(raw.get("id") or ""),
            label=str(raw.get("label") or raw.get("id") or ""),
            year_from=raw.get("year_from"),
            year_to=raw.get("year_to"),
        )
        sliced = apply_attributes(slice_graph(graph, phase), attrs)
        metrics = compute_graph_metrics(sliced, partition=part, advanced=advanced)
        phase_payloads[phase.id] = {"schema": SCHEMA, "graph": sliced, "metrics": metrics}
        ego_series.append(
            {
                "phase": phase.id,
                "label": phase.label,
                **(metrics.get("ego") or {}),
                "nodes": metrics.get("nodes"),
                "edges": metrics.get("edges"),
            }
        )
    bundle_metrics = dict(full_metrics)
    bundle_metrics["by_phase"] = ego_series
    meta = dict(bundle["meta"])
    meta["partition"] = part
    meta["advanced"] = bool(full_metrics.get("advanced"))
    write_run(
        dest,
        meta=meta,
        graph=graph,
        phases=phase_payloads,
        metrics=bundle_metrics,
        attributes=attrs,
    )
    return load_run(cfg, run_id)


def _ego_from_author(author: dict[str, Any], orcid: str) -> AuthorRecord:
    name = str(author.get("display_name") or "").strip()
    return AuthorRecord(
        openalex=short_id(str(author.get("id") or "")),
        orcid=orcid,
        display_name=name,
        fingerprint=name_fingerprint(name),
    )
