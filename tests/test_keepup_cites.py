"""keepup_cites: collection-scoped citer probing and baseline (fake OpenAlex, no network)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

from paperful.config import Config
from paperful import keepup_cites
from paperful.keepup_cites import (
    KeepupCitesError,
    _seed_key,
    _why_line,
    baseline_identities,
    probe_cites,
)


def _cfg(tmp_path: Path) -> Config:
    return Config(
        email="t@example.org",
        out_dir=tmp_path / "out",
        state_dir=tmp_path / "state",
    )


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, highlight=False, width=120), buf


class Lib:
    def __init__(self, dois=("10.1000/a", "10.1000/b"), *, fail=False):
        self.dois = dois
        self.fail = fail

    def resolve_collection(self, path):
        if self.fail:
            raise LookupError(f"No collection matching {path!r}")
        return "root"

    def subtree_keys(self, root):
        return ["K"]

    def items_in_scope(self, keys):
        return [SimpleNamespace(doi=d) for d in self.dois]


def _work(n: int, *, cited=1, doi=True):
    return {
        "id": f"https://openalex.org/W{n}",
        "doi": f"https://doi.org/10.5555/c{n}" if doi else None,
        "display_name": f"Citer {n}",
        "publication_year": 2025,
        "cited_by_count": cited,
        "authorships": [],
        "primary_location": {},
        "open_access": {},
        "type": "article",
        "language": "en",
    }


class Client:
    def __init__(self, seeds=2, citers=None):
        self.seeds = seeds
        self.citers = citers if citers is not None else {}
        self.cite_calls: list[dict] = []

    def works_by_dois(self, dois, select=""):
        return [
            {
                "id": f"https://openalex.org/S{i}",
                "doi": f"https://doi.org/10.1000/{'ab'[i]}",
                "display_name": f"Seed {i}",
            }
            for i in range(self.seeds)
        ]

    def works_citing(self, oa_id, *, limit, from_created_date=None, sort=None):
        self.cite_calls.append({"id": oa_id, "limit": limit, "since": from_created_date})
        return list(self.citers.get(oa_id, []))


def _probe(cfg, client, lib=None, **overrides):
    console, buf = _console()
    kwargs = dict(
        collection="Ocean",
        run_id="keepup:t",
        from_created_date=None,
        per_seed_limit=5,
        max_candidates=50,
        muted=set(),
        seen=set(),
        console=console,
        client=client,
        lookup=lambda *a, **k: None,
        backend=lib or Lib(),
    )
    kwargs.update(overrides)
    rows, polled = probe_cites(cfg, **kwargs)
    return rows, polled, buf.getvalue()


def test_seed_key_prefers_doi():
    assert _seed_key("S1", "10.1/x") == "doi:10.1/x"
    assert _seed_key("S1", "") == "openalex:S1"


def test_why_line_truncates_to_three_titles():
    assert _why_line(4, ["a", "b", "c", "d"]) == "cites 4 of your papers (a; b; c)"
    assert _why_line(1, []) == "cites 1 of your paper"


def test_probe_requires_collection(tmp_path):
    with pytest.raises(KeepupCitesError, match="needs a target collection"):
        _probe(_cfg(tmp_path), Client(), collection="  ")


def test_probe_wraps_library_read_failure(tmp_path):
    with pytest.raises(KeepupCitesError, match="Could not read collection 'Ocean'"):
        _probe(_cfg(tmp_path), Client(), lib=Lib(fail=True))


def test_probe_needs_dois_and_resolved_seeds(tmp_path):
    with pytest.raises(KeepupCitesError, match="No DOIs"):
        _probe(_cfg(tmp_path), Client(), lib=Lib(dois=()))
    with pytest.raises(KeepupCitesError, match="resolved 0 of 2 DOIs"):
        _probe(_cfg(tmp_path), Client(seeds=0))


def test_probe_filters_muted_and_seen_and_passes_since(tmp_path):
    client = Client(citers={"S0": [_work(1), _work(2), _work(3)], "S1": []})
    muted_ident = _probe(_cfg(tmp_path), Client(citers={"S0": [_work(1)]}))[0][0].identity
    seen_ident = _probe(_cfg(tmp_path), Client(citers={"S0": [_work(2)]}))[0][0].identity
    rows, polled, _out = _probe(
        _cfg(tmp_path),
        client,
        muted={muted_ident},
        seen={seen_ident},
        from_created_date="2025-01-01",
    )
    assert polled == 2
    assert [r.ids["doi"] for r in rows] == ["10.5555/c3"]
    assert {c["since"] for c in client.cite_calls} == {"2025-01-01"}
    assert rows[0].keep is True and rows[0].status == "new"


def test_probe_ranks_by_overlap_then_citations_and_caps(tmp_path):
    shared = _work(1, cited=1)
    client = Client(
        citers={
            "S0": [shared, _work(2, cited=500)],
            "S1": [shared, _work(3, cited=900)],
        }
    )
    rows, _polled, _out = _probe(_cfg(tmp_path), client)
    # The paper citing both seeds outranks heavily cited single-seed papers.
    assert [r.ids["doi"] for r in rows][0] == "10.5555/c1"
    assert rows[0].biblio["overlap"] == 2
    assert "Seed 0" in rows[0].why and "Seed 1" in rows[0].why

    capped, _p, out = _probe(_cfg(tmp_path), client, max_candidates=1)
    assert len(capped) == 1
    assert "capped at 1" in out


def test_probe_marks_items_already_in_library(tmp_path):
    client = Client(citers={"S0": [_work(1), _work(2)]})

    def lookup(doi, title, year, **_kw):
        return SimpleNamespace(key="LIB1", title="in library") if doi == "10.5555/c1" else None

    rows, _p, _o = _probe(_cfg(tmp_path), client, lookup=lookup)
    assert [r.ids["doi"] for r in rows] == ["10.5555/c2"]


def test_probe_survives_default_lookup_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "paperful.snowball.command._library_lookup",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("library down")),
    )
    client = Client(citers={"S0": [_work(1)]})
    rows, _p, _o = _probe(_cfg(tmp_path), client, lookup=None)
    assert [r.ids["doi"] for r in rows] == ["10.5555/c1"]


def test_client_helper_prefers_injected_client(tmp_path):
    sentinel = object()
    assert keepup_cites._client(_cfg(tmp_path), sentinel) is sentinel


def test_client_helper_builds_openalex_client(tmp_path, monkeypatch):
    seen = {}

    class FakeOA:
        def __init__(self, *, email, store, store_fail_limit=3):
            seen.update(email=email, store=store, store_fail_limit=store_fail_limit)

    monkeypatch.setattr(keepup_cites, "OpenAlexClient", FakeOA)
    monkeypatch.setattr(keepup_cites, "store_from_config", lambda cfg: "STORE")
    built = keepup_cites._client(_cfg(tmp_path))
    assert isinstance(built, FakeOA)
    assert seen == {"email": "t@example.org", "store": "STORE", "store_fail_limit": 3}


def test_baseline_collects_current_citers(tmp_path):
    client = Client(citers={"S0": [_work(1), _work(2)], "S1": [_work(2), _work(3)]})
    console, _buf = _console()
    seen = baseline_identities(
        _cfg(tmp_path),
        collection="Ocean",
        per_seed_limit=5,
        max_candidates=50,
        console=console,
        client=client,
        backend=Lib(),
    )
    assert len(seen) == 3


def test_baseline_soft_cap_and_errors(tmp_path):
    many = [_work(i) for i in range(1, 12)]
    client = Client(citers={"S0": many, "S1": many})
    console, buf = _console()
    seen = baseline_identities(
        _cfg(tmp_path),
        collection="Ocean",
        per_seed_limit=20,
        max_candidates=2,
        console=console,
        client=client,
        backend=Lib(),
    )
    assert len(seen) == 10  # max_candidates * 5
    assert "baseline soft-capped" in buf.getvalue()
    with pytest.raises(KeepupCitesError, match="Could not read collection"):
        baseline_identities(
            _cfg(tmp_path),
            collection="Ocean",
            per_seed_limit=5,
            max_candidates=5,
            console=console,
            client=client,
            backend=Lib(fail=True),
        )


def test_baseline_skips_seeds_without_openalex_id(tmp_path):
    class NoIdClient(Client):
        def works_by_dois(self, dois, select=""):
            return [{"id": "", "doi": "https://doi.org/10.1000/a"}]

    console, _buf = _console()
    client = NoIdClient()
    assert (
        baseline_identities(
            _cfg(tmp_path),
            collection="Ocean",
            per_seed_limit=5,
            max_candidates=5,
            console=console,
            client=client,
            backend=Lib(),
        )
        == set()
    )
    assert client.cite_calls == []
