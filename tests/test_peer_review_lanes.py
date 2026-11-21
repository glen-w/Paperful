"""Composable peer-review review-lane resolution."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.peer_review_lanes import (
    mode_for_lanes,
    parse_peer_review_lanes,
    resolve_peer_review_lanes,
)
from paperful.peer_review_marg import parse_marg_aspects, resolve_marg_aspects


def test_parse_and_order():
    assert parse_peer_review_lanes(["marg", "reviewers", "marg"]) == (
        "reviewers",
        "marg",
    )
    assert parse_peer_review_lanes("context-web, context") == ("context", "context-web")
    assert parse_peer_review_lanes(["adversary", "marg"]) == ("marg", "adversary")
    assert parse_peer_review_lanes(["verify", "claims", "marg"]) == (
        "marg",
        "claims",
        "verify",
    )
    assert parse_peer_review_lanes(["outline", "adversary"]) == ("adversary", "outline")
    assert parse_peer_review_lanes([]) == ()
    with pytest.raises(ValueError, match="unknown"):
        parse_peer_review_lanes(["nope"])


def test_shims_when_lanes_empty():
    cfg = Config(peer_review_llm=True, peer_review_advanced=True)
    assert resolve_peer_review_lanes(cfg) == ("reviewers", "marg")
    cfg.peer_review_advanced = False
    assert resolve_peer_review_lanes(cfg) == ("reviewers",)
    assert resolve_peer_review_lanes(cfg, llm=False) == ()
    assert resolve_peer_review_lanes(cfg, advanced=True) == ("reviewers", "marg")


def test_config_lanes_ignore_bools_then_cli_overlay():
    cfg = Config(
        peer_review_llm=True,
        peer_review_advanced=True,
        peer_review_lanes=("marg",),
    )
    assert resolve_peer_review_lanes(cfg) == ("marg",)
    assert resolve_peer_review_lanes(cfg, llm=True) == ("reviewers", "marg")
    assert resolve_peer_review_lanes(cfg, advanced=False) == ()


def test_cli_lane_flags_win_as_base():
    cfg = Config(peer_review_llm=True, peer_review_lanes=("marg",))
    assert resolve_peer_review_lanes(cfg, lane_flags=["context"]) == ("context",)
    assert resolve_peer_review_lanes(
        cfg, lane_flags=["context"], llm=True, advanced=True
    ) == ("reviewers", "marg", "context")
    assert resolve_peer_review_lanes(cfg, lane_flags=["adversary"]) == ("adversary",)
    assert resolve_peer_review_lanes(cfg, lane_flags=["outline"]) == ("outline",)
    assert resolve_peer_review_lanes(cfg, lane_flags=["claims", "verify"]) == (
        "claims",
        "verify",
    )


def test_mode_for_lanes():
    assert mode_for_lanes(["reviewers"]) == "default"
    assert mode_for_lanes(["marg"]) == "marg"
    assert mode_for_lanes(["reviewers", "marg"]) == "both"
    assert mode_for_lanes(["context"]) == "context"
    assert mode_for_lanes(["context-web"]) == "context-web"
    assert mode_for_lanes(["adversary"]) == "adversary"
    assert mode_for_lanes(["outline"]) == "outline"
    assert mode_for_lanes(["claims"]) == "claims"
    assert mode_for_lanes(["verify"]) == "verify"


def test_parse_marg_aspects_string_and_default():
    assert parse_marg_aspects(None) == ("experiments", "clarity", "impact")
    assert parse_marg_aspects("theory, policy") == ("theory", "policy")
    assert parse_marg_aspects(["experiments", "experiments"]) == ("experiments",)
    with pytest.raises(ValueError, match="must be an array"):
        parse_marg_aspects(12)
    cfg = Config()
    assert resolve_marg_aspects(cfg) == ("experiments", "clarity", "impact")
    cfg.peer_review_advanced_aspects = ("policy",)
    assert resolve_marg_aspects(cfg) == ("policy",)


def test_suggested_from_llm_dispatches_lane_helpers():
    import inspect

    from paperful import peer_review_llm

    src = inspect.getsource(peer_review_llm.suggested_from_llm)
    for name in ("_run_reviewers", "_run_optional_lane"):
        assert callable(getattr(peer_review_llm, name))
        assert f"{name}(" in src
        assert f"def {name}(" not in src


def test_lane_state_absorb_skips_empty_claims_without_ledger():
    from paperful.peer_review import make_finding
    from paperful.peer_review_llm import _LaneState

    state = _LaneState()
    extra = [make_finding(code="x", severity="info", lane="suggested")]
    state.absorb(
        extra, {"reviewers": [{"id": "a"}], "prompt_sha": "abc", "narrative": "n"}
    )
    assert len(state.out) == 1
    assert state.first_sha == "abc"
    assert state.first_narrative == "n"
    assert state.reviewer_meta == [{"id": "a"}]

    empty = _LaneState()
    empty.absorb(
        [],
        {"skipped": "empty_reply", "narrative": "ignored"},
        keep_if_ledger=True,
        keep_if_narrative=False,
    )
    assert empty.skip_reason == "empty_reply"
    assert empty.first_narrative == ""
