"""In-collection citation counts from OpenAlex reference lists."""

from paperful.snowball.local_cites import load_local_cites
from paperful.snowball.openalex import OpenAlexBudgetExceeded
from tests.conftest import make_item


class _Lib:
    def __init__(self, items):
        self._items = items

    def resolve_collection(self, spec):
        return spec

    def subtree_keys(self, root):
        return ["COL"]

    def items_in_scope(self, keys):
        return list(self._items)


class _Client:
    def __init__(self, works, *, boom=False):
        self.works = works
        self.calls = 0
        self.boom = boom

    def works_by_dois(self, dois):
        self.calls += 1
        if self.boom:
            raise OpenAlexBudgetExceeded("budget", partial=list(self.works))
        return list(self.works)


def _works():
    return [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/a",
            "referenced_works": [
                "https://openalex.org/W1",
                "https://openalex.org/W9",
            ],
        },
        {
            "id": "https://openalex.org/W2",
            "doi": "https://doi.org/10.1000/b",
            "referenced_works": ["https://openalex.org/W9"],
        },
    ]


def test_index_inverts_references_and_drops_self_cites(tmp_path):
    items = [
        make_item(key="A", doi="10.1000/a"),
        make_item(key="B", doi="10.1000/b"),
    ]
    client = _Client(_works())
    index = load_local_cites(
        _Lib(items), "BBNJ", state_dir=tmp_path, client=client
    )
    assert index.count(openalex="W9") == 2
    assert index.count(openalex="W1") == 0
    again = load_local_cites(
        _Lib(items), "BBNJ", state_dir=tmp_path, client=client
    )
    assert again.count(openalex="W9") == 2
    assert client.calls == 1


def test_budget_miss_keeps_partial_index(tmp_path):
    items = [make_item(key="A", doi="10.1000/a"), make_item(key="B", doi="10.1000/b")]
    client = _Client(_works(), boom=True)
    index = load_local_cites(
        _Lib(items), "BBNJ", state_dir=tmp_path, client=client
    )
    assert index.count(openalex="W9") == 2
    assert not (tmp_path / "cites").exists()


def test_library_scope_does_not_resolve_a_collection(tmp_path):
    class Lib(_Lib):
        def resolve_collection(self, spec):
            raise AssertionError(spec)

    items = [make_item(key="A", doi="10.1000/a")]
    client = _Client(
        [
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1000/a",
                "referenced_works": ["https://openalex.org/W9"],
            }
        ]
    )
    index = load_local_cites(
        Lib(items), "ignored", state_dir=tmp_path, client=client, library=True
    )
    assert index.library is True
    assert index.count(openalex="W9") == 1
