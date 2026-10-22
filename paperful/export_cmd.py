"""``paperful export`` implementation (CLI parses flags only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
import typer
from .store import Manifest
from .library import LibraryError


def run_export_library(
    console: Console,
    *,
    dest: Path,
    fmt: str | None,
    collection: list[str],
    library: bool,
    year_from: int | None,
    year_to: int | None,
    item_type: list[str],
    limit: int | None,
    pdfs: bool,
    config: Path | None,
) -> None:
    """Export the scoped library to RIS, BibTeX, or EndNote XML."""
    from . import cli_runtime as cli_mod

    from .interop.load import dump_records, record_from_item_json
    from .store import item_dirname, item_filename, load_json, record_path

    if not collection and not library:
        console.print("[red]Give --collection PATH (repeatable) or --library.[/]")
        raise typer.Exit(1)
    cfg = cli_mod._cfg(config)
    cli_mod._require_manager(cfg)
    kind = (fmt or dest.suffix.lstrip(".") or "").lower().replace("_", "-")
    if kind in {"bib", "biblatex"}:
        kind = "bibtex"
    if kind in {"xml", "enw"}:
        kind = "endnote-xml"
    if kind not in {"ris", "bibtex", "endnote-xml"}:
        console.print("[red]--format must be ris, bibtex, or endnote-xml.[/]")
        raise typer.Exit(1)
    backend = cli_mod._connect(cfg)
    loaded = cli_mod._load_scope(
        backend,
        collection=collection,
        library=library,
        year_from=year_from,
        year_to=year_to,
        item_type=item_type,
    )
    items, scope = loaded.items, loaded.label
    if limit:
        items = items[:limit]
    bundle_dir: Path | None = None
    pdf_dir: Path | None = None
    if kind == "endnote-xml" or pdfs:
        bundle_dir = dest if dest.suffix == "" else dest.parent / dest.stem
        pdf_dir = bundle_dir / "PDF"
        pdf_dir.mkdir(parents=True, exist_ok=True)
    records = []
    copied = 0
    manifest = Manifest(cfg.manifest_path)
    with cli_mod._item_progress() as progress:
        for it in cli_mod._track(progress, "Exporting records")(items):
            rec_json = None
            for folder in it.collection_paths or ["_uncollected"]:
                rec_json = load_json(record_path(cfg.out_dir / folder / item_dirname(it)))
                if rec_json:
                    break
            rec = record_from_item_json(rec_json or {}, None)
            rec["item_type"] = it.item_type
            rec["title"] = it.title
            rec["doi"] = it.doi
            rec["year"] = it.year
            rec["date"] = it.date or rec.get("date") or (str(it.year) if it.year else "")
            rec["publication_title"] = it.publication_title or rec.get("publication_title")
            rec["url"] = it.url
            rec["pmid"] = it.pmid
            rec["abstract"] = it.abstract or rec.get("abstract")
            rec["collection_paths"] = [
                p for p in it.collection_paths if p != "_uncollected"
            ]
            rec["item_key"] = it.key
            pdf_list: list[str] = []
            if pdf_dir is not None and it.has_pdf:
                target = pdf_dir / item_filename(it)
                local = pdf_for(cfg.out_dir, it, manifest)
                try:
                    if local is not None:
                        exported = shutil.copyfile(local, target)
                    else:
                        exported = backend.export_pdf(it, target)
                except LibraryError as exc:
                    cli_mod._exit_env(str(exc), cfg)
                if exported is not None and Path(exported).is_file():
                    pdf_list.append(str(exported))
                    copied += 1
            rec["pdfs"] = pdf_list
            notes = []
            try:
                kids = backend.children(it.key)
            except LibraryError as exc:
                cli_mod._exit_env(str(exc), cfg)
            for ch in kids:
                data = ch.get("data") or {}
                if data.get("itemType") != "note":
                    continue
                html = str(data.get("note") or "")
                if not html:
                    continue
                tags = [
                    t.get("tag")
                    for t in (data.get("tags") or [])
                    if isinstance(t, dict) and t.get("tag")
                ]
                notes.append(
                    {
                        "file": f"{ch.get('key') or 'note'}.html",
                        "html": html,
                        "tag": tags[0] if tags else "paperful-exported",
                    }
                )
            if notes:
                rec["notes"] = notes
            records.append(rec)
    text = dump_records(records, kind)
    if kind == "endnote-xml" and bundle_dir is not None:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        xml_path = bundle_dir / "paperful.xml"
        xml_path.write_text(text, encoding="utf-8")
        (bundle_dir / "README.txt").write_text(
            "Import paperful.xml in EndNote: File → Import → File, "
            "option EndNote Generated XML. PDFs are in PDF/.\n",
            encoding="utf-8",
        )
        console.print(
            f"[green]Wrote[/] {xml_path} ({len(records)} records, {copied} PDFs) for {scope}"
        )
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    extra = f", {copied} PDFs" if copied else ""
    console.print(f"[green]Wrote[/] {dest} ({len(records)} records{extra}) for {scope}")
