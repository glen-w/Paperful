"""Named people lists that poll OpenAlex for new papers.

Distinct from snowball watch (seed crawl + hops), inbox watch (PDF drop
folder), and ResearchGate author-request handoff. Paperful does not schedule
runs. Social sites are not scraped; import a CSV export instead.
"""

from __future__ import annotations

import csv
import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from rich.console import Console
from rich.table import Table

from .config import Config
from .identity import from_seed_tag, library_lookup
from .snowball.authors import name_fingerprint
from .snowball.candidate import Candidate
from .snowball.command import SnowballError, _mark_exists, get_backend
from .snowball.local_openalex import store_from_config
from .snowball.openalex import OpenAlexClient, normalize_orcid, short_id, work_to_candidate

SCHEMA = "paperful.authorwatch.v1"
PERSON_SCHEMA = "paperful.authorwatch.person.v1"
TAG = "paperful-authorwatch"
DEFAULT_MAX_AUTHORS = 50
DEFAULT_PER_AUTHOR_LIMIT = 200
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FILE_SOURCES = ("csv", "json", "orcid")
SOCIAL_SOURCES = ("rg", "researchgate", "linkedin", "academia")
SOCIAL_EXPORT_HINT = (
    "Paperful does not scrape ResearchGate, LinkedIn, or Academia.edu. "
    "Export follows as CSV with name and orcid columns, then: "
    "paperful authorwatch import <name> --file follows.csv --source csv"
)
Lookup = Callable[..., Any]


class AuthorwatchError(SnowballError):
    """User-facing authorwatch failure. Exit code defaults to 2."""


@dataclass
class Person:
    id: str = ""
    display_name: str = ""
    orcid: str = ""
    openalex: str = ""
    affiliation_host: str = ""
    notes: str = ""
    status: str = "unresolved"
    held_candidates: list[dict[str, str]] = field(default_factory=list)
    source: str = "manual"
    added_at: str = ""
    schema: str = PERSON_SCHEMA

    def identity(self) -> str:
        if self.orcid:
            return f"orcid:{self.orcid}"
        if self.openalex:
            return f"openalex:{self.openalex}"
        fp = name_fingerprint(self.display_name)
        return f"name:{fp}" if fp else self.id

    def is_ok(self) -> bool:
        return self.status == "ok" and bool(self.orcid or self.openalex)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Person:
        held = raw.get("held_candidates") or []
        candidates = [dict(row) for row in held if isinstance(row, dict)]
        return cls(
            id=str(raw.get("id") or ""),
            display_name=str(raw.get("display_name") or ""),
            orcid=normalize_orcid(str(raw.get("orcid") or "")),
            openalex=short_id(str(raw.get("openalex") or "")),
            affiliation_host=str(raw.get("affiliation_host") or ""),
            notes=str(raw.get("notes") or ""),
            status=str(raw.get("status") or "unresolved"),
            held_candidates=candidates,
            source=str(raw.get("source") or "manual"),
            added_at=str(raw.get("added_at") or ""),
            schema=str(raw.get("schema") or PERSON_SCHEMA),
        )


@dataclass
class RunResult:
    proposed: int
    exists: int
    skipped_held: int
    ok: int
    held: int
    unresolved: int
    baseline: bool
    backfill_from: str = ""
    polled: int = 0


@dataclass
class ApplyResult:
    created: int
    skipped_exists: int
    already_applied: int
    failed: int
    dry_run: bool


def lists_root(cfg: Config) -> Path:
    return cfg.state_dir / "authorwatch"


def list_dir(cfg: Config, name: str) -> Path:
    _check_name(name)
    return lists_root(cfg) / name


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise AuthorwatchError(
            f"Invalid list name {name!r}. "
            "Use letters, digits, '.', '_' or '-', starting with a letter or digit."
        )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cursor_date(iso: str | None) -> str | None:
    text = str(iso or "").strip()
    if not text:
        return None
    return text[:10]


def _parse_date(raw: str) -> str:
    text = (raw or "").strip()[:10]
    if not _DATE_RE.match(text):
        raise AuthorwatchError("Dates must be YYYY-MM-DD.")
    return text


def _openalex_client(cfg: Config, client: Any = None) -> OpenAlexClient:
    if client is not None:
        return client
    return OpenAlexClient(email=cfg.email, store=store_from_config(cfg))


def save_list(cfg: Config, name: str) -> Path:
    dest = list_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "watch.json"
    if not path.is_file():
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "name": name,
                    "baseline_at": None,
                    "last_run_at": None,
                    "backfill_from": None,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    for leaf, body in (
        ("people.jsonl", ""),
        ("inbox.jsonl", ""),
        ("seen.json", json.dumps({"identities": []}, indent=2) + "\n"),
        ("applied.json", json.dumps({"identities": []}, indent=2) + "\n"),
    ):
        target = dest / leaf
        if not target.is_file():
            target.write_text(body, encoding="utf-8")
    return path


def load_watch(cfg: Config, name: str) -> dict[str, Any]:
    path = list_dir(cfg, name) / "watch.json"
    if not path.is_file():
        raise AuthorwatchError(
            f"Unknown authorwatch list {name!r}. Save one with authorwatch save."
        )
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise AuthorwatchError(f"Corrupt watch ledger at {path}.")
    return body


def _write_watch(cfg: Config, name: str, body: dict[str, Any]) -> None:
    path = list_dir(cfg, name) / "watch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(body)
    body["schema"] = SCHEMA
    body["name"] = name
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def load_people(cfg: Config, name: str) -> list[Person]:
    path = list_dir(cfg, name) / "people.jsonl"
    if not path.is_file():
        return []
    rows: list[Person] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(Person.from_dict(raw))
    return rows


def save_people(cfg: Config, name: str, people: list[Person]) -> None:
    path = list_dir(cfg, name) / "people.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in people:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def _identities_file(cfg: Config, name: str, leaf: str) -> set[str]:
    path = list_dir(cfg, name) / leaf
    if not path.is_file():
        return set()
    body = json.loads(path.read_text(encoding="utf-8"))
    return {str(item) for item in (body.get("identities") or []) if item}


def _save_identities(cfg: Config, name: str, leaf: str, identities: set[str]) -> None:
    dest = list_dir(cfg, name)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / leaf).write_text(
        json.dumps({"identities": sorted(identities)}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_seen(cfg: Config, name: str) -> set[str]:
    return _identities_file(cfg, name, "seen.json")


def save_seen(cfg: Config, name: str, identities: set[str]) -> None:
    _save_identities(cfg, name, "seen.json", identities)


def load_applied(cfg: Config, name: str) -> set[str]:
    return _identities_file(cfg, name, "applied.json")


def save_applied(cfg: Config, name: str, identities: set[str]) -> None:
    _save_identities(cfg, name, "applied.json", identities)


def load_inbox(cfg: Config, name: str) -> list[Candidate]:
    path = list_dir(cfg, name) / "inbox.jsonl"
    if not path.is_file():
        return []
    rows: list[Candidate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(Candidate.from_dict(raw))
    return rows


def append_inbox(cfg: Config, name: str, rows: list[Candidate]) -> None:
    path = list_dir(cfg, name) / "inbox.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def inbox_count(cfg: Config, name: str) -> int:
    return len(load_inbox(cfg, name))


def _new_person_id() -> str:
    return "p_" + secrets.token_hex(4)


def _dedupe_key(person: Person) -> str:
    if person.orcid:
        return f"orcid:{person.orcid}"
    if person.openalex:
        return f"openalex:{person.openalex}"
    fp = name_fingerprint(person.display_name)
    return f"name:{fp}" if fp else person.id


def _merge_person(existing: Person, incoming: Person) -> Person:
    if incoming.orcid:
        existing.orcid = incoming.orcid
    if incoming.openalex:
        existing.openalex = incoming.openalex
    if incoming.display_name and not existing.display_name:
        existing.display_name = incoming.display_name
    if incoming.affiliation_host:
        existing.affiliation_host = incoming.affiliation_host
    if incoming.notes:
        existing.notes = incoming.notes
    if existing.orcid or existing.openalex:
        existing.status = "ok"
        existing.held_candidates = []
    return existing


def add_person(
    cfg: Config,
    name: str,
    *,
    orcid: str = "",
    display_name: str = "",
    affiliation_host: str = "",
    source: str = "manual",
    client: Any = None,
) -> Person:
    save_list(cfg, name)
    cleaned = normalize_orcid(orcid)
    label = (display_name or "").strip()
    host = _host(affiliation_host)
    if not cleaned and not label:
        raise AuthorwatchError("Pass --orcid or --name.")
    if cleaned:
        oa = _openalex_client(cfg, client)
        hit = None
        try:
            if hasattr(oa, "author_by_orcid"):
                hit = oa.author_by_orcid(cleaned)
        except Exception:
            hit = None
        if isinstance(hit, dict):
            label = label or str(hit.get("display_name") or "")
            openalex = short_id(str(hit.get("id") or ""))
        else:
            openalex = ""
        person = Person(
            id=_new_person_id(),
            display_name=label or cleaned,
            orcid=cleaned,
            openalex=openalex,
            affiliation_host=host,
            status="ok",
            source=source,
            added_at=_now(),
        )
    else:
        person = Person(
            id=_new_person_id(),
            display_name=label,
            affiliation_host=host,
            status="unresolved",
            source=source,
            added_at=_now(),
        )
    people = load_people(cfg, name)
    key = _dedupe_key(person)
    for row in people:
        if _dedupe_key(row) == key:
            _merge_person(row, person)
            save_people(cfg, name, people)
            return row
    people.append(person)
    save_people(cfg, name, people)
    return person


def remove_person(cfg: Config, name: str, *, orcid: str = "", person_id: str = "") -> Person:
    people = load_people(cfg, name)
    cleaned = normalize_orcid(orcid)
    want_id = (person_id or "").strip()
    if not cleaned and not want_id:
        raise AuthorwatchError("Pass --orcid or --id.")
    kept: list[Person] = []
    removed: Person | None = None
    for row in people:
        if cleaned and row.orcid == cleaned:
            removed = row
            continue
        if want_id and row.id == want_id:
            removed = row
            continue
        kept.append(row)
    if removed is None:
        raise AuthorwatchError("No matching person on that list.")
    save_people(cfg, name, kept)
    return removed


def _host(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        host = (urlparse(text).hostname or "").lower()
    else:
        host = text.split("/")[0]
    return host[4:] if host.startswith("www.") else host


def _author_preview(row: dict[str, Any]) -> dict[str, str]:
    inst = ""
    for item in row.get("last_known_institutions") or []:
        if isinstance(item, dict) and item.get("display_name"):
            inst = str(item.get("display_name") or "")
            break
    return {
        "display_name": str(row.get("display_name") or ""),
        "orcid": normalize_orcid(str(row.get("orcid") or "")),
        "openalex": short_id(str(row.get("id") or "")),
        "institution": inst,
    }


def _affiliation_match(row: dict[str, Any], host: str) -> bool:
    if not host:
        return True
    blob_parts: list[str] = []
    for item in row.get("last_known_institutions") or []:
        if not isinstance(item, dict):
            continue
        blob_parts.append(str(item.get("display_name") or "").lower())
        blob_parts.append(str(item.get("id") or "").lower())
        homepage = str(item.get("homepage_url") or "").lower()
        blob_parts.append(homepage)
        parsed = _host(homepage)
        if parsed:
            blob_parts.append(parsed)
    blob = " ".join(blob_parts)
    token = host.split(".")[0]
    return host in blob or (len(token) > 3 and token in blob)


def _apply_author_hit(person: Person, row: dict[str, Any]) -> None:
    person.orcid = normalize_orcid(str(row.get("orcid") or "")) or person.orcid
    person.openalex = short_id(str(row.get("id") or "")) or person.openalex
    person.display_name = person.display_name or str(row.get("display_name") or "")
    if person.orcid or person.openalex:
        person.status = "ok"
        person.held_candidates = []


def resolve_people(cfg: Config, name: str, *, client: Any = None) -> list[Person]:
    save_list(cfg, name)
    people = load_people(cfg, name)
    oa = _openalex_client(cfg, client)
    for person in people:
        if person.is_ok():
            if person.orcid and not person.openalex and hasattr(oa, "author_by_orcid"):
                try:
                    hit = oa.author_by_orcid(person.orcid)
                except Exception:
                    hit = None
                if isinstance(hit, dict):
                    _apply_author_hit(person, hit)
            continue
        if person.orcid:
            try:
                hit = oa.author_by_orcid(person.orcid) if hasattr(oa, "author_by_orcid") else None
            except Exception:
                hit = None
            if isinstance(hit, dict):
                _apply_author_hit(person, hit)
            else:
                person.status = "ok" if person.orcid else "unresolved"
            continue
        label = person.display_name.strip()
        if not label:
            person.status = "unresolved"
            continue
        try:
            hits = list(oa.search_authors(label, limit=8) or [])
        except Exception:
            person.status = "unresolved"
            continue
        if person.affiliation_host:
            narrowed = [row for row in hits if _affiliation_match(row, person.affiliation_host)]
            if narrowed:
                hits = narrowed
        if len(hits) == 1:
            _apply_author_hit(person, hits[0])
            if not (person.orcid or person.openalex):
                person.status = "unresolved"
            continue
        if not hits:
            person.status = "unresolved"
            person.held_candidates = []
            continue
        person.status = "held"
        person.held_candidates = [_author_preview(row) for row in hits[:5]]
    save_people(cfg, name, people)
    return people


def _status_counts(people: list[Person]) -> tuple[int, int, int]:
    ok = sum(1 for row in people if row.is_ok())
    held = sum(1 for row in people if row.status == "held")
    unresolved = sum(1 for row in people if row.status == "unresolved")
    return ok, held, unresolved


def next_step(cfg: Config, name: str) -> str:
    people = load_people(cfg, name)
    body = load_watch(cfg, name)
    ok, held, unresolved = _status_counts(people)
    if not people:
        return f"paperful authorwatch add {name} --orcid <ORCID>"
    if ok == 0:
        if held:
            orcid = ""
            for row in people:
                if row.status == "held":
                    for cand in row.held_candidates:
                        if cand.get("orcid"):
                            orcid = cand["orcid"]
                            break
                if orcid:
                    break
            if orcid:
                return f"paperful authorwatch add {name} --orcid {orcid}"
            return f"paperful authorwatch add {name} --orcid <ORCID>"
        return f"paperful authorwatch resolve {name}"
    if not body.get("baseline_at"):
        return f"paperful authorwatch run {name} --backfill-from YYYY-MM-DD"
    pending = [
        row
        for row in load_inbox(cfg, name)
        if row.status == "new" and row.identity not in load_applied(cfg, name)
    ]
    if pending:
        return f"paperful authorwatch apply {name} -C <collection> --apply"
    return f"paperful authorwatch run {name}"


def show_list(cfg: Config, name: str, *, console: Console) -> None:
    body = load_watch(cfg, name)
    people = load_people(cfg, name)
    ok, held, unresolved = _status_counts(people)
    console.print(f"authorwatch {name}")
    console.print(f"  people · {len(people)} (ok {ok} · held {held} · unresolved {unresolved})")
    console.print(f"  inbox · {inbox_count(cfg, name)}")
    console.print(f"  seen · {len(load_seen(cfg, name))}")
    if body.get("baseline_at"):
        console.print(f"  baseline · {body['baseline_at']}")
    else:
        console.print("  baseline · not yet")
    if body.get("last_run_at"):
        console.print(f"  last run · {body['last_run_at']}")
    held_rows = [row for row in people if row.status == "held"]
    if held_rows:
        table = Table(title="held (add --orcid to confirm)")
        table.add_column("Name")
        table.add_column("Candidates")
        for row in held_rows:
            bits = []
            for cand in row.held_candidates:
                label = cand.get("display_name") or ""
                oid = cand.get("orcid") or cand.get("openalex") or ""
                bits.append(f"{label} {oid}".strip())
            table.add_row(row.display_name or row.id, "; ".join(bits) or "(none)")
        console.print(table)
    console.print(f"Next: {next_step(cfg, name)}")


def _candidate_from_work(
    work: dict[str, Any],
    *,
    name: str,
    person: Person,
    gate: str = "dry-run",
) -> Candidate:
    seed_value = person.orcid or person.openalex or person.display_name
    row = work_to_candidate(
        work,
        run_id=f"authorwatch:{name}",
        seed={"type": "authorwatch", "value": seed_value},
        hop=0,
        direction="author",
        why=f"authorwatch:{name}",
        gate=gate,
    )
    row.provenance["authorwatch"] = name
    row.keep = True
    return row


def _lookup(cfg: Config, lookup: Lookup | None, backend: Any) -> Lookup | None:
    if lookup is not None:
        return lookup
    lib = backend
    if lib is None:
        try:
            lib = get_backend(cfg)
        except Exception:
            return None
    try:
        return library_lookup(lib, scope="library", collection="")
    except Exception:
        return None


def _call_lookup(lookup: Lookup, row: Candidate) -> Any:
    doi = row.ids.get("doi") or None
    title = row.biblio.get("title") or None
    year = row.biblio.get("year")
    try:
        return lookup(doi, title, year)
    except TypeError:
        return lookup(doi, title)


def run_list(
    cfg: Config,
    name: str,
    *,
    console: Console,
    client: Any = None,
    lookup: Lookup | None = None,
    backend: Any = None,
    backfill_from: str | None = None,
    max_authors: int = DEFAULT_MAX_AUTHORS,
    per_author_limit: int = DEFAULT_PER_AUTHOR_LIMIT,
) -> RunResult:
    save_list(cfg, name)
    body = load_watch(cfg, name)
    people = load_people(cfg, name)
    ok_people = [row for row in people if row.is_ok()]
    skipped_held = sum(1 for row in people if row.status in {"held", "unresolved"})
    ok_n, held_n, unresolved_n = _status_counts(people)
    is_baseline = not body.get("baseline_at")
    backfill = _parse_date(backfill_from) if backfill_from else ""
    seen = load_seen(cfg, name)
    proposed: list[Candidate] = []
    exists = 0
    polled = 0

    should_poll = bool(backfill) or not is_baseline
    finder = _lookup(cfg, lookup, backend) if should_poll else None
    if should_poll:
        oa = _openalex_client(cfg, client)
        capped = ok_people[: max(0, max_authors)]
        if len(ok_people) > len(capped):
            console.print(
                f"[yellow]capped at {len(capped)} authors "
                f"(of {len(ok_people)}); pass --max-authors[/]"
            )
        created_cursor = None if backfill else _cursor_date(
            body.get("last_run_at") or body.get("baseline_at")
        )
        for person in capped:
            polled += 1
            works = oa.works_by_author(
                orcid=person.orcid,
                openalex=person.openalex,
                limit=max(1, per_author_limit),
                from_created_date=None if backfill else created_cursor,
                from_publication_date=backfill or None,
            )
            for work in works:
                row = _candidate_from_work(work, name=name, person=person)
                key = row.identity
                if not key:
                    continue
                if key in seen:
                    continue
                if finder is not None:
                    found = _call_lookup(finder, row)
                    if found:
                        exists += 1
                        seen.add(key)
                        continue
                seen.add(key)
                proposed.append(row)

    now = _now()
    if proposed:
        append_inbox(cfg, name, proposed)
    save_seen(cfg, name, seen)
    body.update(
        {
            "last_run_at": now,
            "backfill_from": backfill or body.get("backfill_from"),
        }
    )
    if is_baseline:
        body["baseline_at"] = now
    _write_watch(cfg, name, body)

    if is_baseline and not backfill:
        console.print(
            f"baseline · proposed 0 · ok {ok_n} · held {held_n} · unresolved {unresolved_n}"
        )
        console.print(
            f"Next: paperful authorwatch run {name} --backfill-from YYYY-MM-DD"
        )
    else:
        console.print(
            f"ok {ok_n} · held {held_n} · unresolved {unresolved_n} · "
            f"proposed {len(proposed)} · exists {exists} · skipped_held {skipped_held}"
        )
        if proposed:
            console.print(f"Next: paperful authorwatch apply {name} -C <collection> --apply")
        else:
            console.print(f"Next: paperful authorwatch run {name}")
    return RunResult(
        proposed=len(proposed),
        exists=exists,
        skipped_held=skipped_held,
        ok=ok_n,
        held=held_n,
        unresolved=unresolved_n,
        baseline=is_baseline,
        backfill_from=backfill,
        polled=polled,
    )


def apply_list(
    cfg: Config,
    name: str,
    collection: str,
    *,
    console: Console,
    apply: bool = False,
    lookup: Lookup | None = None,
    backend: Any = None,
) -> ApplyResult:
    from .snowball.ingest import create_new

    dest = collection.strip()
    if not dest:
        raise AuthorwatchError("authorwatch apply needs a target collection (-C).")
    rows = load_inbox(cfg, name)
    applied = load_applied(cfg, name)
    pending: list[Candidate] = []
    already = 0
    for row in rows:
        key = row.identity
        if not key:
            continue
        if key in applied:
            already += 1
            continue
        if row.status not in {"new", "exists"}:
            continue
        row.keep = True
        pending.append(row)
    finder = _lookup(cfg, lookup, backend)
    if finder is not None:
        _mark_exists(pending, finder)
    creatable = [row for row in pending if row.status == "new"]
    skipped_exists = sum(1 for row in pending if row.status in {"exists", "version"})
    if not apply:
        table = Table(title=f"authorwatch apply {name} (dry-run)")
        table.add_column("Title")
        table.add_column("DOI")
        table.add_column("Status")
        for row in pending[:25]:
            table.add_row(
                str(row.biblio.get("title") or "")[:80],
                row.ids.get("doi") or "",
                row.status,
            )
        console.print(table)
        console.print(
            f"would create {len(creatable)} · exists {skipped_exists} · "
            f"already applied {already}"
        )
        return ApplyResult(
            created=0,
            skipped_exists=skipped_exists,
            already_applied=already,
            failed=0,
            dry_run=True,
        )
    lib = backend
    if lib is None:
        lib = get_backend(cfg)
    extra = [from_seed_tag({"type": "authorwatch", "value": name}) or f"from-{name}"]
    items, counts = create_new(
        lib,
        creatable,
        dest,
        tag_prefix=TAG,
        extra_tags=extra,
        console=console,
        remarks_surface=cfg.remarks_surface,
    )
    created = int(counts.get("created") or len(items))
    failed = int(counts.get("failed") or 0)
    skipped_exists += int(counts.get("skipped_exists") or 0)
    for row in creatable:
        if row.status == "new" or row.identity:
            key = row.identity
            if key and row.status != "error":
                applied.add(key)
    save_applied(cfg, name, applied)
    console.print(
        f"created {created} · exists {skipped_exists} · "
        f"already applied {already} · failed {failed}"
    )
    if created:
        console.print(f"Next: paperful run -C {dest}")
    return ApplyResult(
        created=created,
        skipped_exists=skipped_exists,
        already_applied=already,
        failed=failed,
        dry_run=False,
    )


def write_briefing(cfg: Config, name: str) -> Path:
    body = load_watch(cfg, name)
    dest = list_dir(cfg, name)
    rows = load_inbox(cfg, name)
    path = dest / "briefing.md"
    lines = [f"# Authorwatch briefing {name}", ""]
    lines.append(f"Inbox `{dest / 'inbox.jsonl'}`.")
    if body.get("baseline_at") and not rows:
        lines.append("Baseline is recorded and the inbox is empty.")
    elif not body.get("baseline_at"):
        lines.append("No baseline yet. `paperful authorwatch run` records one.")
    lines.append("")
    if rows:
        lines.append("## Proposed")
        lines.append("")
        for row in rows:
            title = str(row.biblio.get("title") or "(untitled)")
            doi = row.ids.get("doi") or row.ids.get("openalex") or ""
            year = row.biblio.get("year") or ""
            lines.append(f"- {title} ({year}) {doi}".rstrip())
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _normalize_source(raw: str) -> str:
    text = (raw or "csv").strip().lower()
    if text in {"researchgate"}:
        return "rg"
    return text


def import_file(
    cfg: Config,
    name: str,
    *,
    path: Path | None,
    source: str,
    client: Any = None,
    resolve: bool = True,
) -> list[Person]:
    kind = _normalize_source(source)
    if kind in SOCIAL_SOURCES and path is None:
        raise AuthorwatchError(SOCIAL_EXPORT_HINT)
    if path is None:
        raise AuthorwatchError("Pass --file with a CSV, JSON, or ORCID list.")
    if kind in SOCIAL_SOURCES:
        kind = "csv"
    if kind not in FILE_SOURCES:
        raise AuthorwatchError(
            f"Unknown import source {source!r}. Use csv, json, or orcid "
            "(social follows: export a file; Paperful does not scrape)."
        )
    text_path = path.expanduser()
    if not text_path.is_file():
        raise AuthorwatchError(f"No such file: {text_path}")
    save_list(cfg, name)
    added: list[Person] = []
    if kind == "csv":
        with text_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise AuthorwatchError("CSV needs a header row (name, orcid).")
            fields = {str(key or "").strip().lower(): key for key in reader.fieldnames}
            for raw in reader:
                orcid = _cell(raw, fields, "orcid", "orcid_id")
                display_name = _cell(raw, fields, "name", "display_name", "author")
                if not orcid and not display_name:
                    continue
                person = add_person(
                    cfg,
                    name,
                    orcid=orcid,
                    display_name=display_name,
                    affiliation_host=_cell(raw, fields, "affiliation", "host", "affiliation_host"),
                    source="csv",
                    client=client,
                )
                added.append(person)
    elif kind == "json":
        payload = json.loads(text_path.read_text(encoding="utf-8"))
        rows: list[Any]
        if isinstance(payload, dict):
            rows = list(payload.get("people") or payload.get("authors") or [])
        elif isinstance(payload, list):
            rows = payload
        else:
            raise AuthorwatchError("JSON must be a list or an object with people.")
        for item in rows:
            if isinstance(item, str):
                person = add_person(cfg, name, orcid=item, source="json", client=client)
            elif isinstance(item, dict):
                person = add_person(
                    cfg,
                    name,
                    orcid=str(item.get("orcid") or ""),
                    display_name=str(item.get("name") or item.get("display_name") or ""),
                    affiliation_host=str(
                        item.get("affiliation") or item.get("affiliation_host") or ""
                    ),
                    source="json",
                    client=client,
                )
            else:
                continue
            added.append(person)
    else:
        for line in text_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            added.append(add_person(cfg, name, orcid=line, source="orcid", client=client))
    if resolve:
        resolve_people(cfg, name, client=client)
    return added


def _cell(row: dict[str, Any], fields: dict[str, Any], *names: str) -> str:
    for name in names:
        key = fields.get(name)
        if key is None:
            continue
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def list_summaries(cfg: Config) -> list[tuple[str, int, int]]:
    root = lists_root(cfg)
    if not root.is_dir():
        return []
    out: list[tuple[str, int, int]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        if not (path / "watch.json").is_file() and not (path / "people.jsonl").is_file():
            continue
        try:
            people = load_people(cfg, path.name)
        except AuthorwatchError:
            continue
        ok, _, _ = _status_counts(people)
        out.append((path.name, len(people), ok))
    return out
