"""LLM verbs B/C/D with a stub client — offline, no Ollama."""

from __future__ import annotations

import pytest

from paperful import llm_pdf_match, llm_title, summarize
from paperful.config import Config, _from_dict
from paperful.grounding import budget_slice, metadata_block
from paperful.library import LibraryError
from paperful.llm.client import LLMClientError
from tests.conftest import make_item


class StubLLM:
    provider = "stub"

    def __init__(self, text: str = "", data: dict | None = None, fail: bool = False):
        self.text = text
        self.data = data or {}
        self.fail = fail
        self.calls: list[str] = []

    def check_config(self, model):
        return True, "ok"

    def complete(self, request):
        self.calls.append(request.prompt)
        if self.fail:
            raise LLMClientError("boom")
        return self.text

    def complete_json(self, request):
        self.calls.append(request.prompt)
        if self.fail:
            raise LLMClientError("boom")
        return self.data


PDF_TEXT = (
    "Marine governance and area based management tools in the high seas\n"
    "Smith, Jones. 2019. Journal of Ocean Policy.\n"
    "Abstract: we study governance of marine areas beyond national jurisdiction."
)


@pytest.fixture
def llm_cfg(cfg):
    cfg.llm_enabled = True
    return cfg


def _ground(monkeypatch, module, text=PDF_TEXT):
    monkeypatch.setattr(module, "pdf_text_for", lambda *a, **k: text)


# ---- config nested tables ----------------------------------------------------


def test_nested_tables_parse(tmp_path):
    raw = {
        "llm": {
            "enabled": True,
            "provider": "litellm",
            "model": "gpt-x",
            "api_base": "https://x",
        },
        "browser_agent": {"max_steps": 5, "model": "big"},
        "fix_metadata": {"llm_title": True},
        "lint": {"llm_pdf_match": True, "llm_pdf_match_min_confidence": 2.0},
        "summarize": {"prompt_template": "prompts/p.md", "tag": "  "},
    }
    cfg = _from_dict(raw, tmp_path / "config.toml")
    assert (
        cfg.llm_enabled and cfg.llm_provider == "litellm" and cfg.llm_model == "gpt-x"
    )
    assert cfg.browser_agent_max_steps == 5 and cfg.browser_agent_model == "big"
    assert cfg.fix_metadata_llm_title and cfg.lint_llm_pdf_match
    assert cfg.lint_llm_pdf_match_min_confidence == 1.0  # clamped
    assert cfg.summarize_tag == "paperful-summary"  # blank falls back
    assert cfg.summarize_prompt_template == str((tmp_path / "prompts/p.md").resolve())


def test_defaults_are_off():
    cfg = Config()
    assert not cfg.llm_enabled and not cfg.fix_metadata_llm_title
    assert not cfg.lint_llm_pdf_match and cfg.summarize_prompt_template == "default"


# ---- grounding ---------------------------------------------------------------


def test_budget_slice_keeps_head_and_tail():
    text = (
        "HEAD " * 500
        + "\n1. INTRODUCTION\n"
        + "body " * 2000
        + "\nCONCLUSION\n"
        + "TAIL " * 500
    )
    out = budget_slice(text, 3000)
    assert len(out) <= 3000 + 200
    assert out.startswith("HEAD") and out.rstrip().endswith("TAIL")
    assert "[…]" in out


def test_budget_slice_passthrough_short():
    assert budget_slice("short", 100) == "short"


def test_metadata_block_uses_new_item_fields():
    item = make_item(creator_surnames=["Smith", "Jones"], abstract="An abstract.")
    block = metadata_block(item)
    assert "Authors: Smith, Jones" in block and "Abstract: An abstract." in block
    assert "DOI: 10.1000/test.doi" in block


# ---- Phase B: llm_title ------------------------------------------------------


def test_llm_title_gated_off(llm_cfg, monkeypatch):
    llm_cfg.fix_metadata_llm_title = False
    _ground(monkeypatch, llm_title)
    assert (
        llm_title.propose_llm_title(
            llm_cfg, make_item(), {"title_all_caps"}, None, None
        )
        is None
    )


def test_llm_title_requires_title_code(llm_cfg, monkeypatch):
    llm_cfg.fix_metadata_llm_title = True
    _ground(monkeypatch, llm_title)
    monkeypatch.setattr(
        llm_title, "get_client", lambda cfg: StubLLM(data={"title": "X"})
    )
    assert (
        llm_title.propose_llm_title(llm_cfg, make_item(), {"missing_doi"}, None, None)
        is None
    )


def test_llm_title_grounded_patch(llm_cfg, monkeypatch):
    llm_cfg.fix_metadata_llm_title = True
    _ground(monkeypatch, llm_title)
    stub = StubLLM(data={"title": "Marine governance and area based management tools"})
    monkeypatch.setattr(llm_title, "get_client", lambda cfg: stub)
    item = make_item(title="MARINE GOVERNANCE AND AREA BASED MANAGEMENT TOOLS")
    patch = llm_title.propose_llm_title(llm_cfg, item, {"title_all_caps"}, None, None)
    assert patch is not None and patch.source == "llm_title"
    assert patch.after == {"title": "Marine governance and area based management tools"}
    assert "PDF excerpt" in stub.calls[0]


def test_llm_title_rejects_ungrounded(llm_cfg, monkeypatch):
    llm_cfg.fix_metadata_llm_title = True
    _ground(monkeypatch, llm_title)
    stub = StubLLM(data={"title": "Quantum chromodynamics lattice simulations"})
    monkeypatch.setattr(llm_title, "get_client", lambda cfg: stub)
    item = make_item(title="MARINE GOVERNANCE")
    assert (
        llm_title.propose_llm_title(llm_cfg, item, {"title_all_caps"}, None, None)
        is None
    )


def test_llm_title_continues_on_failure(llm_cfg, monkeypatch):
    llm_cfg.fix_metadata_llm_title = True
    _ground(monkeypatch, llm_title)
    monkeypatch.setattr(llm_title, "get_client", lambda cfg: StubLLM(fail=True))
    assert (
        llm_title.propose_llm_title(llm_cfg, make_item(), {"title_html"}, None, None)
        is None
    )


def test_collect_patches_includes_llm_title(llm_cfg, monkeypatch):
    """Integration: metadata.collect_patches appends the llm_title patch."""
    import httpx

    from paperful import metadata
    from tests.conftest import mock_client

    llm_cfg.fix_metadata_llm_title = True
    llm_cfg.verify_doi = False
    _ground(monkeypatch, llm_title)
    monkeypatch.setattr(
        llm_title,
        "get_client",
        lambda cfg: StubLLM(data={"title": "Marine governance tools"}),
    )
    item = make_item(title="MARINE GOVERNANCE TOOLS", doi=None, url=None)
    patches = metadata.collect_patches(
        mock_client(lambda r: httpx.Response(500)), llm_cfg, [item]
    )
    assert [p.source for p in patches] == ["llm_title"]


# ---- Phase C: pdf identity ---------------------------------------------------


def test_pdf_match_gated_off(llm_cfg, monkeypatch):
    _ground(monkeypatch, llm_pdf_match)
    assert llm_pdf_match.pdf_identity_finding(llm_cfg, make_item(), None, None) is None


def test_pdf_match_mismatch_yields_finding(llm_cfg, monkeypatch):
    llm_cfg.lint_llm_pdf_match = True
    _ground(monkeypatch, llm_pdf_match)
    stub = StubLLM(
        data={"match": False, "confidence": 0.91, "reason": "different authors"}
    )
    monkeypatch.setattr(llm_pdf_match, "get_client", lambda cfg: stub)
    f = llm_pdf_match.pdf_identity_finding(llm_cfg, make_item(), None, None)
    assert f is not None and f.code == "pdf_identity_mismatch"
    assert "different authors" in f.detail and "0.91" in f.detail


def test_pdf_match_ok_yields_none(llm_cfg, monkeypatch):
    llm_cfg.lint_llm_pdf_match = True
    _ground(monkeypatch, llm_pdf_match)
    monkeypatch.setattr(
        llm_pdf_match,
        "get_client",
        lambda cfg: StubLLM(data={"match": True, "confidence": 0.95}),
    )
    assert llm_pdf_match.pdf_identity_finding(llm_cfg, make_item(), None, None) is None


def test_pdf_match_low_confidence_match_flags(llm_cfg, monkeypatch):
    llm_cfg.lint_llm_pdf_match = True
    llm_cfg.lint_llm_pdf_match_min_confidence = 0.8
    _ground(monkeypatch, llm_pdf_match)
    monkeypatch.setattr(
        llm_pdf_match,
        "get_client",
        lambda cfg: StubLLM(data={"match": True, "confidence": 0.3}),
    )
    f = llm_pdf_match.pdf_identity_finding(llm_cfg, make_item(), None, None)
    assert f is not None and "low-confidence" in f.detail


def test_pdf_match_llm_error_is_silent(llm_cfg, monkeypatch):
    llm_cfg.lint_llm_pdf_match = True
    _ground(monkeypatch, llm_pdf_match)
    monkeypatch.setattr(llm_pdf_match, "get_client", lambda cfg: StubLLM(fail=True))
    assert llm_pdf_match.pdf_identity_finding(llm_cfg, make_item(), None, None) is None


def test_pdf_match_no_text_is_silent(llm_cfg, monkeypatch):
    llm_cfg.lint_llm_pdf_match = True
    _ground(monkeypatch, llm_pdf_match, text="")
    monkeypatch.setattr(
        llm_pdf_match, "get_client", lambda cfg: StubLLM(data={"match": False})
    )
    assert llm_pdf_match.pdf_identity_finding(llm_cfg, make_item(), None, None) is None


def test_lint_item_appends_identity_finding(llm_cfg, monkeypatch):
    import httpx

    from paperful.lint import lint_item
    from tests.conftest import mock_client

    llm_cfg.lint_llm_pdf_match = True
    llm_cfg.verify_doi = False
    _ground(monkeypatch, llm_pdf_match)
    monkeypatch.setattr(
        llm_pdf_match,
        "get_client",
        lambda cfg: StubLLM(data={"match": False, "reason": "nope"}),
    )
    findings = lint_item(
        mock_client(lambda r: httpx.Response(500)), llm_cfg, make_item()
    )
    assert any(f.code == "pdf_identity_mismatch" for f in findings)


# ---- Phase D: summarize ------------------------------------------------------


class NoteBackend:
    def __init__(self):
        self.notes: dict[str, tuple[str, str]] = {}
        self.created = 0
        self.updated = 0

    def find_child_note_keys(self, item_key, tag):
        return [
            k
            for k, (parent, t) in self.notes.items()
            if parent == item_key and t == tag
        ]

    def create_or_update_note(self, item_key, html, tag):
        existing = self.find_child_note_keys(item_key, tag)
        if existing:
            self.updated += 1
            return existing[0]
        self.created += 1
        key = f"N{len(self.notes) + 1}"
        self.notes[key] = (item_key, tag)
        return key


def test_summarize_writes_disk_html(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    stub = StubLLM(text="<h2>Objective</h2><p>Study governance.</p>")
    monkeypatch.setattr(summarize, "get_client", lambda cfg: stub)
    item = make_item(has_pdf=True)
    path = summarize.summarize_item(llm_cfg, item, None, None)
    assert path == llm_cfg.summaries_dir / f"{item.key}.html"
    html = path.read_text()
    assert "<h2>Objective</h2>" in html
    assert "paperful ·" in html and llm_cfg.llm_model in html and "prompt " in html
    assert "Document text:" in stub.calls[0] and "Title: " in stub.calls[0]


def test_summarize_requires_pdf(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    with pytest.raises(ValueError):
        summarize.summarize_item(llm_cfg, make_item(has_pdf=False), None, None)


def test_summarize_no_text_raises(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize, text="")
    monkeypatch.setattr(summarize, "get_client", lambda cfg: StubLLM(text="x"))
    with pytest.raises(ValueError):
        summarize.summarize_item(llm_cfg, make_item(has_pdf=True), None, None)


def test_summarize_custom_prompt_changes_sha(llm_cfg, monkeypatch, tmp_path):
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(summarize, "get_client", lambda cfg: StubLLM(text="<p>s</p>"))
    item = make_item(has_pdf=True)
    default_html = summarize.summarize_item(llm_cfg, item, None, None).read_text()
    custom = tmp_path / "custom.md"
    custom.write_text("Summarize in one sentence.")
    llm_cfg.summarize_prompt_template = str(custom)
    custom_html = summarize.summarize_item(llm_cfg, item, None, None).read_text()
    sha_default = default_html.split("prompt ")[-1][:8]
    sha_custom = custom_html.split("prompt ")[-1][:8]
    assert sha_default != sha_custom


def test_summarize_apply_note_is_idempotent(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(summarize, "get_client", lambda cfg: StubLLM(text="<p>s</p>"))
    item = make_item(has_pdf=True)
    backend = NoteBackend()
    summarize.summarize_item(llm_cfg, item, None, None)
    k1 = summarize.apply_summary_note(llm_cfg, backend, item)
    k2 = summarize.apply_summary_note(llm_cfg, backend, item)
    assert k1 == k2 and backend.created == 1 and backend.updated == 1


def test_summarize_apply_without_disk_file(llm_cfg):
    with pytest.raises(FileNotFoundError):
        summarize.apply_summary_note(llm_cfg, NoteBackend(), make_item(has_pdf=True))


def test_summarize_refuses_when_identity_flagged(llm_cfg, monkeypatch):
    llm_cfg.lint_llm_pdf_match = True
    _ground(monkeypatch, summarize)
    _ground(monkeypatch, llm_pdf_match)
    monkeypatch.setattr(
        llm_pdf_match,
        "get_client",
        lambda cfg: StubLLM(data={"match": False, "reason": "wrong"}),
    )
    monkeypatch.setattr(summarize, "get_client", lambda cfg: StubLLM(text="<p>s</p>"))
    item = make_item(has_pdf=True)
    with pytest.raises(summarize.IdentityMismatch):
        summarize.summarize_item(llm_cfg, item, None, None)
    # --force bypasses the gate
    path = summarize.summarize_item(llm_cfg, item, None, None, force=True)
    assert path.is_file()


def test_summarize_remote_footer(llm_cfg, monkeypatch):
    llm_cfg.llm_provider = "litellm"
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(summarize, "get_client", lambda cfg: StubLLM(text="<p>s</p>"))
    html = summarize.summarize_item(
        llm_cfg, make_item(has_pdf=True), None, None
    ).read_text()
    assert "remote LLM" in html


def test_library_error_propagates_from_apply(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(summarize, "get_client", lambda cfg: StubLLM(text="<p>s</p>"))
    item = make_item(has_pdf=True)
    summarize.summarize_item(llm_cfg, item, None, None)

    class Denied:
        def create_or_update_note(self, *a):
            raise LibraryError("no write")

    with pytest.raises(LibraryError):
        summarize.apply_summary_note(llm_cfg, Denied(), item)


# ---- note HTML normalisation (live gemma3 probe emitted Markdown) -------------


def test_to_note_html_converts_markdown():
    md = (
        "## Objective\n\nThe work aims to **define** analytic autoethnography.\n\n"
        "## Key findings\n\n*   **Critique:** overshadowed.\n*   Second point\n\n"
        "## Limitations\n\n- one\n- two\n"
    )
    html = summarize.to_note_html(md)
    assert "##" not in html and "**" not in html
    assert "<h2>Objective</h2>" in html and "<h2>Key findings</h2>" in html
    assert (
        "<p>The work aims to <strong>define</strong> analytic autoethnography.</p>"
        in html
    )
    assert html.count("<ul>") == 2 and html.count("</ul>") == 2
    assert "<li><strong>Critique:</strong> overshadowed.</li>" in html


def test_to_note_html_strips_code_fence_and_keeps_html():
    fenced = "```html\n<h2>Objective</h2>\n<p>ok</p>\n```"
    assert summarize.to_note_html(fenced) == "<h2>Objective</h2>\n<p>ok</p>"


def test_to_note_html_plain_paragraphs():
    assert (
        summarize.to_note_html("one line\nsame para\n\nnext")
        == "<p>one line same para</p>\n<p>next</p>"
    )


def test_to_note_html_empty():
    assert summarize.to_note_html("```\n```") == ""


def test_summarize_normalises_markdown_output(llm_cfg, monkeypatch):
    _ground(monkeypatch, summarize)
    monkeypatch.setattr(
        summarize,
        "get_client",
        lambda cfg: StubLLM(text="## Objective\n\n**bold** text"),
    )
    html = summarize.summarize_item(
        llm_cfg, make_item(has_pdf=True), None, None
    ).read_text()
    assert html.startswith("<h2>Objective</h2>") and "<strong>bold</strong>" in html


def test_to_note_html_mixed_markdown_headings_with_html_paragraphs():
    """Live gemma3 output: Markdown headings but HTML paragraphs/lists."""
    mixed = "## Objective\n\n<p>This work aims.</p>\n\n## Key findings\n\n<ul>\n<li>one</li>\n</ul>\n"
    html = summarize.to_note_html(mixed)
    assert "##" not in html
    assert "<h2>Objective</h2>" in html and "<p>This work aims.</p>" in html
    assert "<ul>" in html and "<li>one</li>" in html and html.count("<ul>") == 1
