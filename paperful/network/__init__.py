"""ORCID ego co-authorship network, phase slices, and SNA metrics."""

from __future__ import annotations

from .attributes import ATTRIBUTE_FIELDS, merge_attributes, seed_attributes, write_attributes_csv
from .build import build_ego_graph, works_to_records
from .metrics import NETWORKX_HINT, compute_graph_metrics, gould_fernandez
from .phases import BBNJ_PHASES, Phase, load_phases, slice_graph
from .run import run_orcid
from .store import (
    GRAPH_KEYS,
    META_KEYS,
    SCHEMA,
    NetworkError,
    list_runs,
    load_run,
    network_root,
    new_run_id,
    run_dir,
    write_run,
)

__all__ = [
    "ATTRIBUTE_FIELDS",
    "BBNJ_PHASES",
    "GRAPH_KEYS",
    "META_KEYS",
    "NETWORKX_HINT",
    "SCHEMA",
    "NetworkError",
    "Phase",
    "build_ego_graph",
    "compute_graph_metrics",
    "gould_fernandez",
    "list_runs",
    "load_phases",
    "load_run",
    "merge_attributes",
    "network_root",
    "new_run_id",
    "run_dir",
    "run_orcid",
    "seed_attributes",
    "slice_graph",
    "works_to_records",
    "write_attributes_csv",
    "write_run",
]
