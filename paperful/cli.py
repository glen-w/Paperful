"""scihub-dl command line."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .attach import Attacher
from .config import Config, load_config
from .pipeline import Pipeline, make_client
from .sources import Context
from .sources.scihub import ping_mirrors
from .store import STATUS_ATTACHED, STATUS_NOT_FOUND, Manifest
from .zot import ZoteroLocal

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Fetch missing PDFs for Zotero items.")
console = Console(highlight=False)

ConfigOpt = typer.Option(None, "--config", "-c", help="Path to config.toml", exists=True, dir_okay=False)


def _cfg(path: Optional[Path]) -> Config:
    cfg = load_config(path)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _zotero() -> ZoteroLocal:
    zl = ZoteroLocal()
    try:
        info = zl.ping()
    except ConnectionError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    except Exception as exc:  # Zotero not running
        console.print(f"[red]Cannot reach Zotero local API at localhost:23119:[/] {exc}\nIs Zotero running?")
        raise typer.Exit(2)
    console.print(
        f"[dim]Zotero {info.get('zotero_version') or '?'}, local API v{info['api_version']}, write support: "
        f"{'yes' if info['supports_write'] else 'no (Zotero 10+ needed)'}[/]"
    )
    return zl


@app.callback()
def _main() -> None:
    """scihub-dl."""


@app.command()
def version() -> None:
    console.print(__version__)


@app.command()
def collections(config: Optional[Path] = ConfigOpt) -> None:
    """Show the collection tree with item counts and how many lack a PDF."""
    _cfg(config)
    zl = _zotero()
    cols = zl.collections()
    counts = zl.collection_counts()
    table = Table(title="Zotero collections (counts include subcollections)")
    table.add_column("Path")
    table.add_column("Items", justify="right")
    table.add_column("No PDF", justify="right")
    table.add_column("Key", style="dim")
    for c in sorted(cols.values(), key=lambda c: c.path.lower()):
        n, missing = counts.get(c.key, (0, 0))
        depth = c.path.count("/")
        table.add_row(("  " * depth) + c.name, str(n), str(missing), c.key)
    console.print(table)


@app.command()
def run(
    collection: list[str] = typer.Option(
        [], "--collection", "-C", help="Collection path/name/key (repeatable). Subcollections included."
    ),
    library: bool = typer.Option(False, "--library", help="Whole library instead of collections."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would be fetched; no network beyond Zotero."),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Stop after N items."),
    no_attach: bool = typer.Option(False, "--no-attach", help="Do not attach PDFs into Zotero."),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Retry items previously marked not_found."),
    sources: Optional[str] = typer.Option(None, "--sources", help="Comma-separated source order override."),
    config: Optional[Path] = ConfigOpt,
) -> None:
    """Find and download PDFs for items lacking one, then attach them."""
    if not collection and not library:
        console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
        raise typer.Exit(1)
    cfg = _cfg(config)
    zl = _zotero()
    source_list = [s.strip() for s in sources.split(",")] if sources else cfg.sources

    keys: list[str] | None
    if library:
        keys = None
        scope = "whole library"
    else:
        keys = []
        for spec in collection:
            try:
                root = zl.resolve_collection(spec)
            except LookupError as exc:
                console.print(f"[red]{exc}[/]")
                raise typer.Exit(1)
            keys.extend(zl.subtree_keys(root))
        scope = ", ".join(collection)

    manifest = Manifest(cfg.manifest_path)
    items = zl.items_lacking_pdf(keys)
    todo = [it for it in items if manifest.should_process(it.key, retry_failed)]
    skipped = len(items) - len(todo)
    if limit:
        todo = todo[:limit]
    console.print(
        f"Scope: [bold]{scope}[/] - {len(items)} items without PDF, {skipped} already handled, "
        f"{len(todo)} to process. Sources: {', '.join(source_list)}"
    )

    if dry_run:
        table = Table(title="Dry run", expand=True)
        table.add_column("Key", style="dim", no_wrap=True)
        table.add_column("Type", no_wrap=True, max_width=14)
        table.add_column("Item", no_wrap=True, overflow="ellipsis", ratio=3)
        table.add_column("DOI (source)", no_wrap=True, overflow="ellipsis", ratio=2)
        table.add_column("URL", no_wrap=True, overflow="ellipsis", ratio=1)
        table.add_column("Collections", no_wrap=True, overflow="ellipsis", ratio=1)
        for it in todo:
            table.add_row(
                it.key,
                it.item_type,
                it.label,
                f"{it.doi} ({it.doi_source})" if it.doi else ("arXiv:" + it.arxiv_id if it.arxiv_id else "-"),
                (it.url or "-")[:60],
                "; ".join(it.collection_paths),
            )
        console.print(table)
        raise typer.Exit(0)

    attacher: Attacher | None = None
    if cfg.attach and not no_attach:
        attacher = Attacher(cfg, zl)
        if not attacher.supports_write():
            console.print("[yellow]Attach disabled: this Zotero has no local write API (upgrade to Zotero 10+). PDFs still saved to disk.[/]")
            attacher = None

    pipe = Pipeline(cfg, manifest, console, sources=source_list, attacher=attacher)
    try:
        stats = pipe.run(todo)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted - progress is in the manifest; rerun to resume.[/]")
        stats = pipe.stats
    _print_stats(stats, cfg)


def _print_stats(stats, cfg: Config) -> None:
    console.print(
        f"\n[bold]Done.[/] ok={stats.ok} attached={stats.attached} attach_failed={stats.attach_failed} "
        f"not_found={stats.not_found} no_identifier={stats.no_identifier} captcha={stats.captcha} error={stats.error}"
    )
    if stats.by_source:
        console.print("By source: " + ", ".join(f"{k}={v}" for k, v in sorted(stats.by_source.items())))
    console.print(f"[dim]PDFs: {cfg.out_dir}   manifest: {cfg.manifest_path}[/]")


@app.command()
def attach(config: Optional[Path] = ConfigOpt, limit: Optional[int] = typer.Option(None, "--limit", "-n")) -> None:
    """Attach already-downloaded PDFs (status ok / attach_failed) into Zotero."""
    cfg = _cfg(config)
    zl = _zotero()
    manifest = Manifest(cfg.manifest_path)
    attacher = Attacher(cfg, zl)
    if not attacher.supports_write():
        console.print("[red]This Zotero has no local write API. Upgrade to Zotero 10+ to attach.[/]")
        raise typer.Exit(2)
    pending = manifest.pending_attach()
    if limit:
        pending = pending[:limit]
    console.print(f"{len(pending)} PDFs to attach")
    pipe = Pipeline(cfg, manifest, console, attacher=attacher)
    done = 0
    try:
        for rec in pending:
            if pipe.attach_record(rec):
                done += 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
    console.print(f"[bold]Attached {done}/{len(pending)}[/]")


@app.command()
def report(
    config: Optional[Path] = ConfigOpt,
    not_found: bool = typer.Option(False, "--not-found", help="List not_found items with DOIs."),
    status: Optional[str] = typer.Option(None, "--status", help="List items with this status."),
) -> None:
    """Summarise the manifest: counts by status and by source."""
    cfg = _cfg(config)
    manifest = Manifest(cfg.manifest_path)
    if not manifest.records:
        console.print("Manifest is empty.")
        raise typer.Exit(0)
    table = Table(title=f"{len(manifest.records)} items in manifest")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for k, v in sorted(manifest.counts().items(), key=lambda kv: -kv[1]):
        table.add_row(k, str(v))
    console.print(table)
    by_src = manifest.by_source()
    if by_src:
        console.print("PDFs by source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_src.items(), key=lambda kv: -kv[1])))
    want = STATUS_NOT_FOUND if not_found else status
    if want:
        rows = [r for r in manifest.records.values() if r.status == want]
        t = Table(title=f"{len(rows)} items with status {want}")
        t.add_column("Key", style="dim")
        t.add_column("Title")
        t.add_column("DOI")
        t.add_column("Attempts" if want != STATUS_ATTACHED else "Path")
        for r in sorted(rows, key=lambda r: r.title.lower()):
            t.add_row(r.itemKey, r.title[:70], r.doi or "-", (r.path or "") if want == STATUS_ATTACHED else " ".join(r.attempts)[-90:])
        console.print(t)


@app.command()
def mirrors(config: Optional[Path] = ConfigOpt) -> None:
    """Ping the configured Sci-Hub mirrors."""
    cfg = _cfg(config)
    ctx = Context(config=cfg, client=make_client(cfg))
    for mirror, status in ping_mirrors(ctx):
        colour = "green" if status == "HTTP 200" else "red"
        console.print(f"[{colour}]{status:<10}[/] {mirror}")


@app.command("ezproxy")
def ezproxy_cmd(
    config: Optional[Path] = ConfigOpt,
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the EZProxy login page"),
) -> None:
    """Check / refresh the campus EZProxy session.

    1. Set ezproxy_base in config.toml to your library's login?url= prefix.
    2. This command opens that login in your browser (SSO).
    3. After you are logged in, export Netscape cookies for the proxy host
       (e.g. *.idm.oclc.org) to the path shown — see README “Campus EZProxy”.
    4. Re-run with --no-open to verify Session OK.
    """
    import webbrowser

    from .sources import ezproxy as ez

    cfg = _cfg(config)
    cookie_path = cfg.ezproxy_cookies or (cfg.state_dir / "ezproxy-cookies.txt")
    if not cfg.ezproxy_base:
        console.print("[red]ezproxy_base is empty in config.toml[/]")
        console.print("Set it to your library EZProxy prefix, e.g. https://PREFIX.idm.oclc.org/login?url=")
        raise typer.Exit(1)

    console.print(f"Proxy:   {cfg.ezproxy_base}")
    console.print(f"Cookies: {cookie_path}")
    login_url = ez.proxify("https://www.sciencedirect.com/", cfg.ezproxy_base)
    if open_browser:
        console.print(f"Opening login: {login_url}")
        webbrowser.open(login_url)

    if not cookie_path.is_file():
        console.print(
            "\n[yellow]No cookie file yet.[/] Complete library SSO in the browser, then export a\n"
            "Netscape cookies.txt that includes your EZProxy host (e.g. [bold]*.idm.oclc.org[/]) to:\n"
            f"  {cookie_path}\n"
            "Firefox: addons.mozilla.org → cookies.txt · Chrome: Get cookies.txt LOCALLY\n"
            "Details: README → Campus EZProxy\n"
            "Then re-run: [bold]uv run scihub-dl ezproxy --no-open[/]"
        )
        raise typer.Exit(2)

    ctx = Context(config=cfg, client=make_client(cfg))
    ok, detail = ez.session_ok(ctx)
    if ok:
        console.print(f"[green]Session OK[/] — {detail}")
    else:
        console.print(f"[red]Session not ready:[/] {detail}")
        console.print("Log in again in the browser, re-export cookies, then retry.")
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
