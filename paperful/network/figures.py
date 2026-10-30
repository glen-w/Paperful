"""Optional matplotlib phase-ego PNGs. GUI uses D3; this is CLI ``--figures``."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_phase_figures(dest: Path, phases: dict[str, dict[str, Any]]) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
    except ImportError as exc:
        raise RuntimeError(
            "Phase figures need matplotlib and networkx. "
            "Install with: uv sync --extra network"
        ) from exc

    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for slug, payload in phases.items():
        graph = payload.get("graph") or payload
        nodes = list(graph.get("nodes") or [])
        edges = list(graph.get("edges") or [])
        ego_id = str((graph.get("ego") or {}).get("id") or "")
        g = nx.Graph()
        labels: dict[str, str] = {}
        for node in nodes:
            nid = str(node.get("id") or "")
            if not nid:
                continue
            g.add_node(nid)
            labels[nid] = str(node.get("display_name") or nid).split(",")[0][:22]
        for edge in edges:
            left = str(edge.get("a") or "")
            right = str(edge.get("b") or "")
            if left and right:
                g.add_edge(left, right)
        fig, ax = plt.subplots(figsize=(8, 6))
        if g.number_of_nodes():
            pos = nx.spring_layout(g, seed=7)
            colors = ["#c46a2a" if n == ego_id else "#3d5a80" for n in g.nodes]
            sizes = [420 if n == ego_id else 180 for n in g.nodes]
            nx.draw_networkx_nodes(g, pos, ax=ax, node_color=colors, node_size=sizes)
            nx.draw_networkx_edges(g, pos, ax=ax, alpha=0.45)
            nx.draw_networkx_labels(g, pos, labels, ax=ax, font_size=7)
        ax.set_axis_off()
        title = str((graph.get("phase") or {}).get("label") or slug)
        ax.set_title(title)
        path = dest / f"{slug}.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        written.append(path)
    return written
