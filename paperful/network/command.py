"""``paperful network`` implementation (CLI parses flags only)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ..agent_json import envelope
from .store import NetworkError, list_runs, load_run, run_dir


def _call(action: Any) -> Any:
    from .. import cli_runtime as cli_mod

    try:
        return action()
    except NetworkError as exc:
        cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(exc.code) from exc
    except ValueError as exc:
        cli_mod.console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


def run_network_orcid(
    console: Console,
    orcid: str,
    *,
    phases: str,
    partition: str,
    max_works: int,
    max_alters: int,
    figures: bool,
    fmt: str,
    config: Path | None,
    run_id: str | None = None,
    out_dir: Path | None = None,
) -> None:
    from .. import cli_runtime as cli_mod
    from .run import run_orcid

    cfg = cli_mod._cfg(config)
    bundle = _call(
        lambda: run_orcid(
            cfg,
            orcid,
            phases=phases,
            partition=partition,
            max_works=max_works,
            max_alters=max_alters,
            figures=figures,
            run_id=run_id,
            dest=out_dir,
        )
    )
    _emit_run(console, bundle, fmt=fmt, command="network orcid")


def run_network_show(
    console: Console,
    run_id: str,
    *,
    phase: str,
    fmt: str,
    config: Path | None,
) -> None:
    from .. import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    bundle = _call(lambda: load_run(cfg, run_id))
    if (phase or "").strip():
        slug = phase.strip()
        payload = (bundle.get("phases") or {}).get(slug)
        if not payload:
            console.print(f"[red]Phase {slug!r} is not in run {run_id}.[/]")
            raise typer.Exit(1)
        bundle = {
            **bundle,
            "metrics": payload.get("metrics") or {},
            "graph": payload.get("graph") or bundle.get("graph"),
        }
    _emit_run(console, bundle, fmt=fmt, command="network show")


def run_network_export(
    console: Console,
    run_id: str,
    *,
    fmt: str,
    dest: Path | None,
    phase: str,
    config: Path | None,
) -> None:
    from .. import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    bundle = _call(lambda: load_run(cfg, run_id))
    graph = bundle.get("graph") or {}
    if (phase or "").strip():
        payload = (bundle.get("phases") or {}).get(phase.strip()) or {}
        graph = payload.get("graph") or graph
    out = dest if dest is not None else run_dir(cfg, run_id) / f"export.{fmt}"
    kind = (fmt or "csv").strip().lower()
    if kind == "csv":
        path = _write_edge_csv(out.with_suffix(".csv") if out.suffix != ".csv" else out, graph)
    elif kind in {"gexf", "graphml"}:
        path = _call(lambda: _write_nx(out, graph, kind))
    else:
        console.print("[red]Export format must be csv, gexf, or graphml.[/]")
        raise typer.Exit(1)
    console.print(f"Wrote [bold]{path}[/]")


def run_network_attributes(
    console: Console,
    run_id: str,
    *,
    write_template: bool,
    config: Path | None,
) -> None:
    from .. import cli_runtime as cli_mod
    from .attributes import seed_attributes, write_attributes_csv
    from .run import refresh_metrics

    cfg = cli_mod._cfg(config)
    bundle = _call(lambda: load_run(cfg, run_id))
    dest = Path(bundle["path"]) / "attributes.csv"
    if write_template or not dest.is_file():
        rows = bundle.get("attributes") or seed_attributes(bundle.get("graph") or {})
        write_attributes_csv(dest, rows)
        console.print(f"Wrote [bold]{dest}[/] — edit region / discipline / sector / career_stage, then re-run without --write-template to recompute brokerage.")
        return
    updated = _call(lambda: refresh_metrics(cfg, run_id))
    console.print(
        f"Reloaded attributes and metrics for [bold]{updated['run_id']}[/] · "
        f"{updated['meta'].get('nodes')} nodes"
    )


def run_network_list(console: Console, *, config: Path | None, fmt: str) -> None:
    from .. import cli_runtime as cli_mod

    cfg = cli_mod._cfg(config)
    rows = list_runs(cfg)
    if fmt == "json":
        print(
            json.dumps(
                envelope(
                    command="network list",
                    summary={"runs": len(rows)},
                    items=rows,
                    paths={},
                    flags={},
                ),
                indent=2,
            )
        )
        return
    if not rows:
        console.print("No network runs yet. Try [bold]paperful network orcid <orcid>[/].")
        return
    table = Table(title="Network runs")
    table.add_column("run_id")
    table.add_column("name")
    table.add_column("orcid")
    table.add_column("nodes")
    table.add_column("built")
    for row in rows:
        table.add_row(
            str(row.get("run_id") or ""),
            str(row.get("display_name") or ""),
            str(row.get("orcid") or ""),
            str(row.get("nodes") or 0),
            str(row.get("built_at") or ""),
        )
    console.print(table)


def _emit_run(console: Console, bundle: dict[str, Any], *, fmt: str, command: str) -> None:
    meta = bundle.get("meta") or {}
    metrics = bundle.get("metrics") or {}
    if fmt == "json":
        print(
            json.dumps(
                envelope(
                    command=command,
                    summary={
                        "run_id": bundle.get("run_id") or meta.get("run_id"),
                        "orcid": meta.get("orcid"),
                        "display_name": meta.get("display_name"),
                        "nodes": meta.get("nodes") or metrics.get("nodes"),
                        "edges": meta.get("edges") or metrics.get("edges"),
                        "advanced": metrics.get("advanced"),
                        "partition": metrics.get("partition") or meta.get("partition"),
                    },
                    items=metrics.get("by_phase") or [],
                    paths={"run": bundle.get("path") or ""},
                    flags={"partition": meta.get("partition") or "none"},
                    report={"ego": metrics.get("ego"), "brokerage": metrics.get("brokerage")},
                ),
                indent=2,
            )
        )
        return
    console.print(
        f"[bold]{meta.get('display_name') or meta.get('orcid') or bundle.get('run_id')}[/] · "
        f"{meta.get('nodes')} nodes · {meta.get('edges')} edges · "
        f"run [bold]{bundle.get('run_id') or meta.get('run_id')}[/]"
    )
    if metrics.get("advanced_error"):
        console.print(f"[yellow]{metrics['advanced_error']}[/]")
    ego = metrics.get("ego") or {}
    table = Table(title="Ego across phases")
    table.add_column("phase")
    table.add_column("nodes", justify="right")
    table.add_column("degree", justify="right")
    table.add_column("betweenness", justify="right")
    table.add_column("constraint", justify="right")
    series = metrics.get("by_phase") or []
    if series:
        for row in series:
            table.add_row(
                str(row.get("label") or row.get("phase") or ""),
                str(row.get("nodes") or ""),
                _fmt_num(row.get("degree")),
                _fmt_num(row.get("betweenness")),
                _fmt_num(row.get("constraint")),
            )
    else:
        table.add_row(
            "all",
            str(metrics.get("nodes") or ""),
            _fmt_num(ego.get("degree")),
            _fmt_num(ego.get("betweenness")),
            _fmt_num(ego.get("constraint")),
        )
    console.print(table)
    roles = (ego.get("brokerage") or metrics.get("brokerage") or {}).get("roles") or {}
    if roles:
        role_table = Table(title="Gould–Fernandez roles (ego)")
        role_table.add_column("role")
        role_table.add_column("count", justify="right")
        for name, count in roles.items():
            role_table.add_row(str(name), str(count))
        console.print(role_table)
    path = bundle.get("path") or ""
    if path:
        console.print(f"Wrote [bold]{path}[/]")


def _fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.3f}"


def _write_edge_csv(path: Path, graph: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["a", "b", "weight", "years"])
        for edge in graph.get("edges") or []:
            years = ";".join(str(y) for y in (edge.get("years") or []))
            writer.writerow([edge.get("a"), edge.get("b"), edge.get("weight"), years])
    return path


def _write_nx(path: Path, graph: dict[str, Any], kind: str) -> Path:
    try:
        import networkx as nx
    except ImportError as exc:
        raise NetworkError(
            "gexf/graphml export needs NetworkX. uv sync --extra network"
        ) from exc
    g = nx.Graph()
    for node in graph.get("nodes") or []:
        nid = str(node.get("id") or "")
        if nid:
            g.add_node(nid, **{k: node.get(k) for k in node if k != "id"})
    for edge in graph.get("edges") or []:
        left, right = str(edge.get("a") or ""), str(edge.get("b") or "")
        if left and right:
            g.add_edge(left, right, weight=int(edge.get("weight") or 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "gexf":
        target = path if path.suffix == ".gexf" else path.with_suffix(".gexf")
        nx.write_gexf(g, target)
    else:
        target = path if path.suffix == ".graphml" else path.with_suffix(".graphml")
        nx.write_graphml(g, target)
    return target
