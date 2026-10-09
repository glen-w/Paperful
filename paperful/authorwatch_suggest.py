"""Corpus- and OpenAlex-grounded author suggestions for authorwatch lists."""

from __future__ import annotations

import secrets
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from .authors_report import harvest
from .authorwatch import (
    AuthorwatchError,
    Person,
    _dedupe_key,
    _openalex_client,
    load_people,
    save_list,
)
from .config import Config
from .snowball.authors import (
    load_promoted_packs,
    name_fingerprint,
    pack_slug,
    records_from_authorships,
)
from .snowball.openalex import OpenAlexBudgetExceeded, normalize_orcid, short_id

SUGGESTION_SCHEMA = "paperful.authorwatch.suggestion.v1"
METHODS = ("corpus", "most_cited", "coauthor", "mix")
DEFAULT_SUGGEST_LIMIT = 15
_COAUTHOR_WORKS = 25


@dataclass
class Suggestion:
    id: str = ""
    display_name: str = ""
    orcid: str = ""
    openalex: str = ""
    method: str = ""
    score: float = 0.0
    why: str = ""
    status: str = "pending"
    pollable: bool = False
    schema: str = SUGGESTION_SCHEMA

    def identity(self) -> str:
        if self.orcid:
            return f"orcid:{self.orcid}"
        if self.openalex:
            return f"openalex:{self.openalex}"
        fp = name_fingerprint(self.display_name)
        return f"name:{fp}" if fp else self.id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Suggestion:
        return cls(
            id=str(raw.get("id") or ""),
            display_name=str(raw.get("display_name") or ""),
            orcid=normalize_orcid(str(raw.get("orcid") or "")),
            openalex=short_id(str(raw.get("openalex") or "")),
            method=str(raw.get("method") or ""),
            score=float(raw.get("score") or 0),
            why=str(raw.get("why") or ""),
            status=str(raw.get("status") or "pending"),
            pollable=bool(raw.get("pollable")),
            schema=str(raw.get("schema") or SUGGESTION_SCHEMA),
        )


def _new_suggestion_id() -> str:
    return "sug_" + secrets.token_hex(4)


def _member_keys(people: list[Person]) -> set[str]:
    return {_dedupe_key(row) for row in people}


def _pending_keys(rows: list[Suggestion]) -> set[str]:
    return {row.identity() for row in rows if row.status == "pending"}


def _normalize_scores(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    hi = max(values.values()) or 1.0
    lo = min(values.values())
    span = hi - lo
    if span <= 0:
        return {k: 1.0 for k in values}
    return {k: (v - lo) / span for k, v in values.items()}


def _author_row_hit(client: Any, name: str) -> dict[str, Any] | None:
    try:
        hits = list(client.search_authors(name, limit=3) or [])
    except OpenAlexBudgetExceeded:
        raise
    except Exception:
        return None
    if len(hits) != 1:
        return None
    return hits[0]


def _candidate_from_author(
    row: dict[str, Any],
    *,
    method: str,
    score: float,
    why: str,
) -> Suggestion:
    orcid = normalize_orcid(str(row.get("orcid") or ""))
    openalex = short_id(str(row.get("id") or ""))
    display = str(row.get("display_name") or "") or orcid or openalex
    pollable = bool(orcid or openalex)
    return Suggestion(
        id=_new_suggestion_id(),
        display_name=display,
        orcid=orcid,
        openalex=openalex,
        method=method,
        score=score,
        why=why,
        status="pending",
        pollable=pollable,
    )


def _corpus_candidates(items: list[Any], *, method: str) -> list[Suggestion]:
    report = harvest(items, min_count=1)
    out: list[Suggestion] = []
    max_count = report.authors[0].count if report.authors else 1
    for row in report.authors:
        score = row.count / max_count if max_count else 0.0
        out.append(
            Suggestion(
                id=_new_suggestion_id(),
                display_name=row.name,
                method=method,
                score=score,
                why=f"{row.count} item(s) in collection",
                status="pending",
                pollable=False,
            )
        )
    return out


def _enrich_cited(
    cfg: Config,
    candidates: list[Suggestion],
    *,
    client: Any,
    method: str,
) -> list[Suggestion]:
    out: list[Suggestion] = []
    cited_by_key: dict[str, float] = {}
    for cand in candidates:
        name = cand.display_name.strip()
        if not name:
            continue
        rank_key = cand.identity() or name.casefold()
        if cand.orcid or cand.openalex:
            cited = 0.0
            if hasattr(client, "author_by_orcid") and cand.orcid:
                try:
                    hit = client.author_by_orcid(cand.orcid)
                except OpenAlexBudgetExceeded:
                    raise
                except Exception:
                    hit = None
                if isinstance(hit, dict):
                    cited = float(hit.get("cited_by_count") or 0)
            cited_by_key[rank_key] = cited
            out.append(cand)
            continue
        hit = _author_row_hit(client, name)
        if not hit:
            out.append(cand)
            continue
        cited = float(hit.get("cited_by_count") or 0)
        enriched = _candidate_from_author(
            hit,
            method=method,
            score=cand.score,
            why=f"{cand.why}; cited_by_count={int(cited)}",
        )
        rank_key = enriched.identity() or name.casefold()
        cited_by_key[rank_key] = cited
        out.append(enriched)
    if not cited_by_key:
        return out
    norm = _normalize_scores(cited_by_key)
    merged: list[Suggestion] = []
    for cand in out:
        key = cand.identity() or cand.display_name.casefold()
        if key in norm and (cand.orcid or cand.openalex):
            merged.append(
                Suggestion(
                    id=cand.id or _new_suggestion_id(),
                    display_name=cand.display_name,
                    orcid=cand.orcid,
                    openalex=cand.openalex,
                    method=method,
                    score=norm[key],
                    why=cand.why if "cited_by_count" in cand.why else (
                        f"{cand.why}; cited_by_count={int(cited_by_key[key])}"
                        if cand.why
                        else f"cited_by_count={int(cited_by_key[key])}"
                    ),
                    status="pending",
                    pollable=True,
                )
            )
        else:
            merged.append(cand)
    merged.sort(key=lambda r: (-r.score, r.display_name.casefold()))
    return merged


def accumulate_coauthors_from_works(
    works: list[dict[str, Any]],
    *,
    seed_key: str,
    skip_keys: set[str],
) -> tuple[Counter[str], dict[str, tuple[str, str, str]]]:
    counts: Counter[str] = Counter()
    nodes: dict[str, tuple[str, str, str]] = {}
    for work in works or []:
        _, records = records_from_authorships(work.get("authorships"))
        for rec in records:
            ident = ""
            if rec.get("orcid"):
                ident = f"orcid:{rec['orcid']}"
            elif rec.get("openalex"):
                ident = f"openalex:{rec['openalex']}"
            elif rec.get("fingerprint"):
                ident = f"name:{rec['fingerprint']}"
            if not ident or ident == seed_key or ident in skip_keys:
                continue
            counts[ident] += 1
            nodes[ident] = (
                str(rec.get("display_name") or ""),
                normalize_orcid(str(rec.get("orcid") or "")),
                short_id(str(rec.get("openalex") or "")),
            )
    return counts, nodes


def _coauthor_candidates(
    cfg: Config,
    people: list[Person],
    collection: str,
    *,
    client: Any,
    method: str,
) -> list[Suggestion]:
    seeds = [row for row in people if row.is_ok()]
    counts: Counter[str] = Counter()
    nodes: dict[str, tuple[str, str, str]] = {}
    member_keys = _member_keys(people)
    if seeds:
        for person in seeds[:10]:
            try:
                works = client.works_by_author(
                    orcid=person.orcid,
                    openalex=person.openalex,
                    limit=_COAUTHOR_WORKS,
                )
            except OpenAlexBudgetExceeded:
                raise
            except Exception:
                continue
            seed_key = _dedupe_key(person)
            part_counts, part_nodes = accumulate_coauthors_from_works(
                works,
                seed_key=seed_key,
                skip_keys=member_keys,
            )
            counts.update(part_counts)
            nodes.update(part_nodes)
    if not counts and collection:
        slug = pack_slug(collection)
        for pack in load_promoted_packs(cfg):
            if pack.collection and pack.collection != collection:
                if pack_slug(pack.collection) != slug and pack.name != slug:
                    continue
            for author in pack.authors[:20]:
                ident = ""
                if author.orcid:
                    ident = f"orcid:{author.orcid}"
                elif author.openalex:
                    ident = f"openalex:{author.openalex}"
                elif author.fingerprint:
                    ident = f"name:{author.fingerprint}"
                if not ident:
                    continue
                counts[ident] += max(1, author.frequency)
                nodes[ident] = (author.name, author.orcid, author.openalex)
    max_v = max(counts.values()) if counts else 1
    out: list[Suggestion] = []
    for ident, count in counts.most_common(50):
        display, orcid, openalex = nodes.get(ident, ("", "", ""))
        if not display and not orcid:
            continue
        out.append(
            Suggestion(
                id=_new_suggestion_id(),
                display_name=display or orcid,
                orcid=orcid,
                openalex=openalex,
                method=method,
                score=count / max_v,
                why=f"{count} shared work(s) with list or pack",
                status="pending",
                pollable=bool(orcid or openalex),
            )
        )
    return out


def _mix_candidates(corpus: list[Suggestion], cited: list[Suggestion]) -> list[Suggestion]:
    by_name: dict[str, tuple[float, float, Suggestion]] = {}
    for row in corpus:
        key = row.display_name.casefold()
        by_name[key] = (row.score, 0.0, row)
    for row in cited:
        key = row.display_name.casefold()
        prev = by_name.get(key)
        if prev:
            by_name[key] = (prev[0], row.score, prev[2])
        else:
            by_name[key] = (0.0, row.score, row)
    out: list[Suggestion] = []
    for key, (c_score, t_score, base) in by_name.items():
        mix = (c_score + t_score) / 2.0
        out.append(
            Suggestion(
                id=_new_suggestion_id(),
                display_name=base.display_name,
                orcid=base.orcid,
                openalex=base.openalex,
                method="mix",
                score=mix,
                why=f"corpus={c_score:.2f} · cited={t_score:.2f}",
                status="pending",
                pollable=base.pollable or bool(base.orcid or base.openalex),
            )
        )
    out.sort(key=lambda r: (-r.score, r.display_name.casefold()))
    return out


def load_collection_items(cfg: Config, collection: str, backend: Any = None) -> list[Any]:
    coll = (collection or "").strip()
    if not coll:
        raise AuthorwatchError("authorwatch suggest needs a target collection (-C).")
    from . import cli as cli_mod

    if backend is None:
        backend = cli_mod._connect(cfg, quiet=True)
    loaded = cli_mod._load_scope(
        backend,
        collection=[coll],
        library=False,
        year_from=None,
        year_to=None,
        item_type=[],
        json_out=True,
    )
    return list(loaded.items)


def suggest_people(
    cfg: Config,
    name: str,
    *,
    collection: str,
    method: str = "corpus",
    limit: int = DEFAULT_SUGGEST_LIMIT,
    client: Any = None,
    backend: Any = None,
    items: list[Any] | None = None,
) -> list[Suggestion]:
    """Rank candidates and append pending rows to suggestions.jsonl."""
    from .authorwatch import append_suggestions, load_suggestions

    kind = (method or "corpus").strip().lower()
    if kind not in METHODS:
        raise AuthorwatchError(f"Unknown method {method!r}. Use corpus, most_cited, coauthor, or mix.")
    cap = max(1, min(int(limit or DEFAULT_SUGGEST_LIMIT), 100))
    save_list(cfg, name)
    people = load_people(cfg, name)
    blocked = _member_keys(people)
    existing = load_suggestions(cfg, name)
    blocked |= _pending_keys(existing)
    oa = _openalex_client(cfg, client)
    if items is None:
        items = load_collection_items(cfg, collection, backend=backend)
    generated: list[Suggestion] = []
    try:
        if kind == "corpus":
            generated = _corpus_candidates(items, method=kind)
        elif kind == "most_cited":
            corpus = _corpus_candidates(items, method=kind)
            generated = _enrich_cited(cfg, corpus, client=oa, method=kind)
            generated.sort(key=lambda r: (-r.score, r.display_name.casefold()))
        elif kind == "coauthor":
            generated = _coauthor_candidates(
                cfg, people, collection, client=oa, method=kind
            )
        else:
            corpus = _corpus_candidates(items, method="corpus")
            cited = _enrich_cited(cfg, corpus, client=oa, method="most_cited")
            generated = _mix_candidates(corpus, cited)
    except OpenAlexBudgetExceeded as exc:
        raise AuthorwatchError(str(exc)) from exc
    fresh: list[Suggestion] = []
    for row in generated:
        if row.identity() in blocked:
            continue
        fresh.append(row)
        blocked.add(row.identity())
        if len(fresh) >= cap:
            break
    if fresh:
        append_suggestions(cfg, name, fresh)
    return fresh
