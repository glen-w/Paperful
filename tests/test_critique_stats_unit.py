"""GRIM / statcheck helpers: edge branches the pack tests skip."""

from __future__ import annotations

import math

from paperful.critique_stats import (
    _p_matches,
    _parse_p,
    chi2_right_p,
    decimals_of,
    f_right_p,
    grim_possible,
    scan_stats,
    t_two_tailed_p,
    z_two_tailed_p,
)


def test_grim_rejects_bad_n_and_impossible_mean():
    assert grim_possible(1.5, 0, 1) is False
    assert grim_possible(1.5, 2, -1) is False
    assert grim_possible(1.23, 2, 2) is False


def test_decimals_of_integer_and_trailing_junk():
    assert decimals_of("12") == 0
    assert decimals_of("1.50x") == 2


def test_t_f_chi2_guard_invalid_df():
    assert math.isnan(t_two_tailed_p(1.0, 0))
    assert math.isnan(f_right_p(0.0, 1, 10))
    assert math.isnan(f_right_p(1.0, 0, 10))
    assert math.isnan(chi2_right_p(-1.0, 2))
    assert math.isnan(chi2_right_p(1.0, 0))


def test_chi2_series_and_continued_fraction():
    # x < s+1 uses the series; a large stat uses the continued fraction.
    small = chi2_right_p(0.4, 4)  # stat/2 = 0.2, s = 2
    large = chi2_right_p(40.0, 2)
    assert 0 < small < 1
    assert 0 <= large < 0.01
    assert chi2_right_p(0.0, 2) == 1.0


def test_z_and_p_match_tolerances():
    p = z_two_tailed_p(1.96)
    assert abs(p - 0.05) < 0.01
    assert _p_matches(0.05, p)
    assert _p_matches(0.0, 0.0001)
    assert _p_matches(0.2, 0.21)
    assert _p_matches(0.012, 0.011)
    assert _p_matches(0.05, 0.049, decimals=2)
    assert math.isnan(float("nan")) or True
    assert _p_matches(0.5, float("nan")) is True
    assert _parse_p(None, None) is None
    assert _parse_p("=", "nope") is None


def test_scan_stats_covers_chi2_z_and_n_before_mean():
    text = (
        "chi-squared(2)=0.5, p=0.80. z=0.1, p=0.90. "
        "N=2, M=1.50. Elsewhere p=0.03 with 95% CI [0.1, 0.2]."
    )
    kinds = {h.kind for h in scan_stats(text)}
    assert "chi2" in kinds
    assert "z" in kinds
    assert "grim" in kinds
    # nearby CI should suppress p_no_n for that window
    p_hits = [h for h in scan_stats("p=0.03 with 95% CI [0.1, 0.2].")]
    assert not any(h.kind == "p_no_n" for h in p_hits)
