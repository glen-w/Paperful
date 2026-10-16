"""Saturation stopping rules, borrowed from SnowBallSLR and not vendored.

Every configured rule is scored at each labeled hop. Only the selected rule
stops the crawl, plus an empty frontier or a depth / candidate ceiling.
Capture–recapture recall is intentionally absent.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RULES = ("off", "marginal_yield", "asymptotic_coverage", "budget", "any")
SCHEMA = "paperful.snowball.stop.v1"


@dataclass(frozen=True)
class StopParams:
    rule: str = "off"
    eps: float = 0.01
    k: int = 2
    tau: float = 0.95
    min_points: int = 4
    max_screened: int = 0


@dataclass(frozen=True)
class IterationStat:
    iteration: int
    screened: int
    included: int


@dataclass
class StopDecision:
    rule: str
    triggered: bool
    value: float | None
    threshold: float | None
    rationale: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_stop_rule(value: Any) -> str:
    text = str(value or "off").strip().lower().replace("-", "_")
    aliases = {
        "off": "off",
        "none": "off",
        "false": "off",
        "0": "off",
        "marginal_yield": "marginal_yield",
        "yield": "marginal_yield",
        "asymptotic_coverage": "asymptotic_coverage",
        "asymptote": "asymptotic_coverage",
        "coverage": "asymptotic_coverage",
        "budget": "budget",
        "any": "any",
    }
    if text not in aliases:
        raise ValueError(
            "stop_rule must be off, marginal_yield, asymptotic_coverage, budget, or any."
        )
    return aliases[text]


def parse_stop_params(
    *,
    rule: Any,
    eps: Any = 0.01,
    k: Any = 2,
    tau: Any = 0.95,
    min_points: Any = 4,
    max_screened: Any = 0,
) -> StopParams:
    parsed = parse_stop_rule(rule)
    eps_f = float(eps)
    k_i = int(k)
    tau_f = float(tau)
    points = int(min_points)
    cap = int(max_screened)
    if not 0 < eps_f <= 1:
        raise ValueError("stop_eps must be greater than 0 and at most 1.")
    if k_i < 1:
        raise ValueError("stop_k must be at least 1.")
    if not 0 < tau_f <= 1:
        raise ValueError("stop_tau must be greater than 0 and at most 1.")
    if points < 2:
        raise ValueError("stop_min_points must be at least 2.")
    if cap < 0:
        raise ValueError("stop_max_screened must be 0 or a positive count.")
    return StopParams(
        rule=parsed,
        eps=eps_f,
        k=k_i,
        tau=tau_f,
        min_points=points,
        max_screened=cap,
    )


def _yield(stat: IterationStat) -> float | None:
    if stat.screened <= 0:
        return None
    return stat.included / stat.screened


def marginal_yield(history: list[IterationStat], params: StopParams) -> StopDecision:
    """New Keeps / screened stays below ``eps`` for ``k`` hops, and not before hop ``k+1``."""
    if not history:
        return StopDecision(
            "marginal_yield",
            False,
            None,
            params.eps,
            "Marginal yield has no labeled hop yet.",
        )
    last = history[-1]
    rate = _yield(last)
    window = history[-params.k :]
    rates = [_yield(stat) for stat in window]
    streak = (
        len(history) >= params.k + 1
        and len(window) == params.k
        and all(item is not None and item < params.eps for item in rates)
    )
    shown = "not computed" if rate is None else f"{rate:.3f}"
    if streak:
        rationale = (
            f"Citation searching stopped after iteration {last.iteration}: "
            f"new Keeps per work screened stayed below {params.eps:g} "
            f"for {params.k} consecutive iterations "
            f"(latest {last.included} of {last.screened})."
        )
    else:
        rationale = (
            f"Iteration {last.iteration} kept {last.included} of {last.screened} "
            f"screened works (yield {shown}). marginal_yield needs {params.k} "
            f"consecutive iterations below {params.eps:g} and does not fire "
            f"before iteration {params.k + 1}."
        )
    return StopDecision(
        "marginal_yield",
        streak,
        rate,
        params.eps,
        rationale,
        {"k": params.k, "streak": [None if item is None else round(item, 6) for item in rates]},
    )


def _fit_asymptote(cumulative: list[int]) -> tuple[float, float] | None:
    """Fit ``N(i) = N_inf * (1 - exp(-lambda * i))``. Deterministic grid, no scipy."""
    if len(cumulative) < 2 or cumulative[-1] <= 0:
        return None
    observed = cumulative[-1]
    step = max(1, observed // 25)
    best: tuple[float, float] | None = None
    best_err: float | None = None
    ceiling = max(observed + step, observed * 4)
    n_inf = observed
    while n_inf <= ceiling:
        for lam_i in range(1, 41):
            lam = lam_i * 0.05
            err = 0.0
            for index, count in enumerate(cumulative, start=1):
                pred = n_inf * (1.0 - math.exp(-lam * index))
                err += (pred - count) ** 2
            if best_err is None or err < best_err:
                best_err = err
                best = (float(n_inf), lam)
        n_inf += step
    if best is None or best[0] < observed:
        return None
    return best


def asymptotic_coverage(history: list[IterationStat], params: StopParams) -> StopDecision:
    cumulative: list[int] = []
    total = 0
    for stat in history:
        total += stat.included
        cumulative.append(total)
    if len(history) < params.min_points:
        return StopDecision(
            "asymptotic_coverage",
            False,
            None,
            params.tau,
            (
                f"Asymptotic coverage needs {params.min_points} labeled iterations "
                f"({len(history)} so far)."
            ),
            {"fit_failed": True, "reason": "too_few"},
        )
    fit = _fit_asymptote(cumulative)
    observed = cumulative[-1] if cumulative else 0
    if fit is None:
        return StopDecision(
            "asymptotic_coverage",
            False,
            None,
            params.tau,
            "Asymptotic coverage did not fit a ceiling above the Keeps so far.",
            {"fit_failed": True},
        )
    n_inf, lam = fit
    ratio = observed / n_inf if n_inf else 0.0
    fired = ratio >= params.tau
    if fired:
        rationale = (
            f"Citation searching stopped after iteration {history[-1].iteration}: "
            f"{observed} Keeps reached {params.tau:g} of the fitted ceiling {n_inf:.0f}."
        )
    else:
        rationale = (
            f"Iteration {history[-1].iteration} has {observed} Keeps against a fitted "
            f"ceiling of {n_inf:.0f} (fraction {ratio:.3f}, threshold {params.tau:g})."
        )
    return StopDecision(
        "asymptotic_coverage",
        fired,
        ratio,
        params.tau,
        rationale,
        {"n_inf": n_inf, "lambda": lam, "observed": observed, "fit_failed": False},
    )


def budget_rule(history: list[IterationStat], params: StopParams) -> StopDecision:
    screened = sum(stat.screened for stat in history)
    if params.max_screened <= 0:
        return StopDecision(
            "budget",
            False,
            float(screened),
            None,
            "No screening cap is set.",
            {"max_screened": 0},
        )
    fired = screened >= params.max_screened
    if fired:
        rationale = (
            f"Citation searching stopped after iteration {history[-1].iteration}: "
            f"{screened} works had been screened, meeting the cap of {params.max_screened}."
        )
    else:
        rationale = (
            f"{screened} works screened so far, under the cap of {params.max_screened}."
        )
    return StopDecision(
        "budget",
        fired,
        float(screened),
        float(params.max_screened),
        rationale,
        {"screened": screened},
    )


def exhaustion(*, frontier_empty: bool, iteration: int) -> StopDecision:
    if frontier_empty:
        rationale = (
            f"Citation searching stopped after iteration {iteration}: "
            "no kept work remained to expand."
        )
    else:
        rationale = f"Iteration {iteration} still has kept works to expand."
    return StopDecision(
        "exhaustion",
        frontier_empty,
        0.0 if frontier_empty else 1.0,
        None,
        rationale,
    )


def depth_ceiling_decision(*, next_hop: int, ceiling: int, iteration: int) -> StopDecision:
    fired = next_hop > ceiling
    if fired:
        rationale = (
            f"Citation searching stopped after hop {ceiling}: "
            f"the depth ceiling is {ceiling}."
        )
    else:
        rationale = f"Hop {next_hop} is within the depth ceiling of {ceiling}."
    return StopDecision(
        "depth",
        fired,
        float(next_hop),
        float(ceiling),
        rationale,
        {"next_hop": next_hop, "ceiling": ceiling, "iteration": iteration},
    )


def candidate_ceiling_decision(*, room: int, iteration: int) -> StopDecision:
    if room < 0:
        return StopDecision(
            "max_candidates",
            False,
            None,
            None,
            "max_candidates is unlimited.",
        )
    fired = room <= 0
    if fired:
        rationale = (
            f"Citation searching stopped after iteration {iteration}: "
            "max_candidates has no room for another hop."
        )
    else:
        rationale = f"{room} candidate slots remain under max_candidates."
    return StopDecision(
        "max_candidates",
        fired,
        float(room),
        0.0,
        rationale,
    )


def evaluate(
    history: list[IterationStat],
    params: StopParams,
    *,
    frontier_empty: bool,
    next_hop: int,
    depth_ceiling: int,
    candidate_room: int,
) -> list[StopDecision]:
    iteration = history[-1].iteration if history else 0
    return [
        marginal_yield(history, params),
        asymptotic_coverage(history, params),
        budget_rule(history, params),
        exhaustion(frontier_empty=frontier_empty, iteration=iteration),
        depth_ceiling_decision(next_hop=next_hop, ceiling=depth_ceiling, iteration=iteration),
        candidate_ceiling_decision(room=candidate_room, iteration=iteration),
    ]


def terminating(decisions: list[StopDecision], rule: str) -> StopDecision | None:
    """The selected rule, otherwise an empty frontier or a safety ceiling."""
    by_name = {item.rule: item for item in decisions}
    if rule == "any":
        for name in ("marginal_yield", "asymptotic_coverage", "budget", "exhaustion"):
            item = by_name.get(name)
            if item is not None and item.triggered:
                return item
    elif rule not in {"off", ""}:
        chosen = by_name.get(rule)
        if chosen is not None and chosen.triggered:
            return chosen
    for name in ("exhaustion", "depth", "max_candidates"):
        item = by_name.get(name)
        if item is not None and item.triggered:
            return item
    return None


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return raw


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def append_decisions(path: Path, iteration: int, decisions: list[StopDecision]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for item in decisions:
            row = item.to_dict()
            row["iteration"] = iteration
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
