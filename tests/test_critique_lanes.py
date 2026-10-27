"""Composable critique review-lane resolution."""

from __future__ import annotations

import pytest

from paperful.config import Config
from paperful.critique_lanes import (
    mode_for_lanes,
    parse_critique_lanes,
    resolve_critique_lanes,
)
from paperful.critique_marg import parse_marg_aspects, resolve_marg_aspects


def test_parse_and_order():
    assert parse_critique_lanes(["marg", "reviewers", "marg"]) == (
        "reviewers",
        "marg",
    )
    assert parse_critique_lanes("context-web, context") == ("context", "context-web")
    assert parse_critique_lanes(["adversary", "marg"]) == ("marg", "adversary")
    assert parse_critique_lanes(["verify", "claims", "marg"]) == (
        "marg",
        "claims",
        "verify",
    )
    assert parse_critique_lanes([]) == ()
    with pytest.raises(ValueError, match="unknown"):
        parse_critique_lanes(["nope"])


def test_shims_when_lanes_empty():
    cfg = Config(critique_llm=True, critique_advanced=True)
    assert resolve_critique_lanes(cfg) == ("reviewers", "marg")
    cfg.critique_advanced = False
    assert resolve_critique_lanes(cfg) == ("reviewers",)
    assert resolve_critique_lanes(cfg, llm=False) == ()
    assert resolve_critique_lanes(cfg, advanced=True) == ("reviewers", "marg")


def test_config_lanes_ignore_bools_then_cli_overlay():
    cfg = Config(
        critique_llm=True,
        critique_advanced=True,
        critique_lanes=("marg",),
    )
    assert resolve_critique_lanes(cfg) == ("marg",)
    assert resolve_critique_lanes(cfg, llm=True) == ("reviewers", "marg")
    assert resolve_critique_lanes(cfg, advanced=False) == ()


def test_cli_lane_flags_win_as_base():
    cfg = Config(critique_llm=True, critique_lanes=("marg",))
    assert resolve_critique_lanes(cfg, lane_flags=["context"]) == ("context",)
    assert resolve_critique_lanes(
        cfg, lane_flags=["context"], llm=True, advanced=True
    ) == ("reviewers", "marg", "context")
    assert resolve_critique_lanes(cfg, lane_flags=["adversary"]) == ("adversary",)
    assert resolve_critique_lanes(cfg, lane_flags=["claims", "verify"]) == (
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
    cfg.critique_advanced_aspects = ("policy",)
    assert resolve_marg_aspects(cfg) == ("policy",)
