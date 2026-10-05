"""Co-author graph, field packs, and simple-host heuristics for author-site preflight."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import Config
from .candidate import Candidate
from .openalex import normalize_orcid, short_id

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PACK_SCHEMA = "paperful.author_pack.v1"
GRAPH_SCHEMA = "paperful.snowball.coauthors.v1"
_UNSAFE = re.compile(r"[^a-z0-9]+")
_SKIP_HOSTS = (
    "researchgate.net",
    "academia.edu",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "scholar.google",
    "doi.org",
    "youtube.com",
    "wikipedia.org",
    "orcid.org",
)
_SIMPLE_HOSTS = (
    "github.io",
    "weebly.com",
    "wordpress.com",
    "wixsite.com",
    "sites.google.com",
    "gitlab.io",
)


@dataclass
class AuthorRecord:
    openalex: str = ""
    orcid: str = ""
    display_name: str = ""
    fingerprint: str = ""

    def identity(self) -> str:
        if self.openalex:
            return f"openalex:{self.openalex}"
        if self.orcid:
            return f"orcid:{self.orcid}"
        return f"name:{self.fingerprint}" if self.fingerprint else ""

    def to_dict(self) -> dict[str, str]:
        return {
            "openalex": self.openalex,
            "orcid": self.orcid,
            "display_name": self.display_name,
            "fingerprint": self.fingerprint,
        }


@dataclass
class PackAuthor:
    openalex: str = ""
    orcid: str = ""
    name: str = ""
    fingerprint: str = ""
    base_host: str = ""
    listing_url: str = ""
    source: str = ""
    verified_at: str = ""
    frequency: int = 0
    degree: int = 0

    def identity(self) -> str:
        if self.openalex:
            return f"openalex:{self.openalex}"
        if self.orcid:
            return f"orcid:{self.orcid}"
        return f"name:{self.fingerprint}" if self.fingerprint else ""


@dataclass
class AuthorPack:
    schema: str = PACK_SCHEMA
    name: str = ""
    collection: str = ""
    status: str = "proposed"
    authors: list[PackAuthor] = field(default_factory=list)

    def to_toml(self) -> str:
        lines = [
            f'schema = "{self.schema}"',
            f'name = "{_esc(self.name)}"',
            f'collection = "{_esc(self.collection)}"',
            f'status = "{self.status}"',
            "",
        ]
        for row in self.authors:
            lines.append("[[authors]]")
            lines.append(f'openalex = "{_esc(row.openalex)}"')
            lines.append(f'orcid = "{_esc(row.orcid)}"')
            lines.append(f'name = "{_esc(row.name)}"')
            lines.append(f'fingerprint = "{_esc(row.fingerprint)}"')
            lines.append(f'base_host = "{_esc(row.base_host)}"')
            lines.append(f'listing_url = "{_esc(row.listing_url)}"')
            lines.append(f'source = "{_esc(row.source)}"')
            lines.append(f'verified_at = "{_esc(row.verified_at)}"')
            lines.append(f"frequency = {int(row.frequency)}")
            lines.append(f"degree = {int(row.degree)}")
            lines.append("")
        return "\n".join(lines)


def name_fingerprint(display_name: str) -> str:
    parts = [p for p in re.split(r"\s+", (display_name or "").strip()) if p]
    if not parts:
        return ""
    last = re.sub(r"[^a-z0-9]+", "", parts[-1].lower())
    first = re.sub(r"[^a-z0-9]+", "", parts[0].lower())
    initial = first[:1] if first else ""
    if not last:
        return ""
    return f"{last}|{initial}"


def records_from_authorships(
    authorships: list[Any] | None,
) -> tuple[list[str], list[dict[str, str]]]:
    names: list[str] = []
    records: list[dict[str, str]] = []
    for row in authorships or []:
        if not isinstance(row, dict):
            continue
        author = row.get("author") or {}
        if not isinstance(author, dict):
            author = {}
        name = (author.get("display_name") or row.get("raw_author_name") or "").strip()
        oa = short_id(str(author.get("id") or ""))
        orcid = normalize_orcid(str(author.get("orcid") or ""))
        rec = AuthorRecord(
            openalex=oa,
            orcid=orcid,
            display_name=name,
            fingerprint=name_fingerprint(name),
        )
        if name:
            names.append(name)
        if rec.identity():
            records.append(rec.to_dict())
    return names, records


def author_records_from_row(row: Candidate) -> list[AuthorRecord]:
    raw = row.biblio.get("author_records") or []
    out: list[AuthorRecord] = []
    if isinstance(raw, list) and raw:
        for item in raw:
            if not isinstance(item, dict):
                continue
            rec = AuthorRecord(
                openalex=str(item.get("openalex") or ""),
                orcid=normalize_orcid(str(item.get("orcid") or "")),
                display_name=str(item.get("display_name") or ""),
                fingerprint=str(item.get("fingerprint") or "")
                or name_fingerprint(str(item.get("display_name") or "")),
            )
            if rec.identity():
                out.append(rec)
        return out
    for name in row.biblio.get("authors") or []:
        rec = AuthorRecord(
            display_name=str(name), fingerprint=name_fingerprint(str(name))
        )
        if rec.identity():
            out.append(rec)
    return out


def build_coauthor_graph(
    rows: list[Candidate], *, max_authors: int = 15
) -> dict[str, Any]:
    freq: Counter[str] = Counter()
    nodes: dict[str, AuthorRecord] = {}
    edges: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        people = author_records_from_row(row)
        seen_ids: list[str] = []
        for rec in people:
            key = rec.identity()
            if not key:
                continue
            freq[key] += 1
            nodes[key] = rec
            if key not in seen_ids:
                seen_ids.append(key)
        for i, left in enumerate(seen_ids):
            for right in seen_ids[i + 1 :]:
                pair = (left, right) if left < right else (right, left)
                edges[pair] += 1
    degree: Counter[str] = Counter()
    for left, right in edges:
        degree[left] += 1
        degree[right] += 1
    ranked = sorted(freq.keys(), key=lambda k: (-freq[k], -degree[k], k))
    cap = max(1, int(max_authors or 15))
    top = ranked[:cap]
    return {
        "schema": GRAPH_SCHEMA,
        "nodes": [
            {
                **nodes[key].to_dict(),
                "id": key,
                "frequency": int(freq[key]),
                "degree": int(degree[key]),
            }
            for key in top
        ],
        "edges": [
            {"a": a, "b": b, "weight": w}
            for (a, b), w in sorted(edges.items(), key=lambda kv: -kv[1])
            if a in set(top) and b in set(top)
        ],
        "ranked": top,
    }


def write_coauthors(dest: Path, graph: dict[str, Any]) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "coauthors.json"
    path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    return path


def pack_slug(collection: str, *, name: str = "") -> str:
    raw = (name or collection or "snowball").strip().lower()
    slug = _UNSAFE.sub("-", raw).strip("-")
    return (slug or "snowball")[:80]


def packs_dir(cfg: Config) -> Path:
    return cfg.state_dir / "author-packs"


def pack_path(cfg: Config, slug: str, *, promoted: bool = False) -> Path:
    suffix = "" if promoted else ".proposed"
    return packs_dir(cfg) / f"{slug}{suffix}.toml"


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_blocked_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == skip or host.endswith("." + skip) for skip in _SKIP_HOSTS)


def is_simple_host(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or is_blocked_host(host):
        return False
    if any(host == s or host.endswith("." + s) for s in _SIMPLE_HOSTS):
        return True
    path = (parsed.path or "").lower()
    if host.endswith(".edu") and any(
        tok in path for tok in ("/faculty", "/people", "/~", "/staff")
    ):
        return True
    if host.endswith(".ac.uk") and any(
        tok in path for tok in ("/people", "/staff", "/profile")
    ):
        return True
    labels = host.split(".")
    if len(labels) == 2 and labels[-1] in {"com", "net", "org", "io", "me"}:
        return True
    return False


def classify_listing_url(url: str) -> str:
    text = (url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return ""
    if is_blocked_host(host_of(text)):
        return ""
    if is_simple_host(text):
        return text
    return ""


def load_pack_file(path: Path) -> AuthorPack | None:
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    if not isinstance(raw, dict):
        return None
    authors: list[PackAuthor] = []
    for row in raw.get("authors") or []:
        if not isinstance(row, dict):
            continue
        authors.append(
            PackAuthor(
                openalex=str(row.get("openalex") or ""),
                orcid=normalize_orcid(str(row.get("orcid") or "")),
                name=str(row.get("name") or ""),
                fingerprint=str(row.get("fingerprint") or ""),
                base_host=str(row.get("base_host") or ""),
                listing_url=str(row.get("listing_url") or ""),
                source=str(row.get("source") or ""),
                verified_at=str(row.get("verified_at") or ""),
                frequency=int(row.get("frequency") or 0),
                degree=int(row.get("degree") or 0),
            )
        )
    return AuthorPack(
        schema=str(raw.get("schema") or PACK_SCHEMA),
        name=str(raw.get("name") or path.stem),
        collection=str(raw.get("collection") or ""),
        status=str(raw.get("status") or "proposed"),
        authors=authors,
    )


def write_pack(path: Path, pack: AuthorPack) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pack.to_toml(), encoding="utf-8")
    return path


def load_promoted_packs(cfg: Config) -> list[AuthorPack]:
    root = packs_dir(cfg)
    if not root.is_dir():
        return []
    out: list[AuthorPack] = []
    for path in sorted(root.glob("*.toml")):
        if ".proposed." in path.name:
            continue
        pack = load_pack_file(path)
        if pack is None or pack.status == "proposed":
            continue
        out.append(pack)
    return out


def item_matches_pack(item: Any, pack: AuthorPack) -> PackAuthor | None:
    surnames = [s.lower() for s in (getattr(item, "creator_surnames", None) or []) if s]
    first = (getattr(item, "first_author", None) or "").lower()
    for author in pack.authors:
        if not author.listing_url and not author.base_host:
            continue
        last = author.fingerprint.split("|", 1)[0] if author.fingerprint else ""
        name_last = (author.name.split() or [""])[-1].lower()
        token = last or name_last
        if token and any(token in s.lower() or s.lower() in token for s in surnames):
            return author
        if token and token in first:
            return author
    return None


def matching_author(item: Any, cfg: Config) -> PackAuthor | None:
    for pack in load_promoted_packs(cfg):
        hit = item_matches_pack(item, pack)
        if hit is not None:
            return hit
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _esc(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')
