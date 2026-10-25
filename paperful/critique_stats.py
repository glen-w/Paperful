"""Stdlib GRIM and a statcheck-style p-value subset. No scipy/R."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# t(df)=x, p=y  /  F(df1, df2)=x, p=y  /  χ²(df)=x  /  z=x  /  r=x, n=N, p=y
_T = re.compile(
    r"\bt\s*\(\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:[^p]{0,40}?p\s*[<=>]\s*([<>]?=?)\s*(0?\.\d+|1(?:\.0+)?))?",
    re.I,
)
_F = re.compile(
    r"\bF\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:[^p]{0,40}?p\s*[<=>]\s*([<>]?=?)\s*(0?\.\d+|1(?:\.0+)?))?",
    re.I,
)
_CHI = re.compile(
    r"(?:χ\s*²|chi[\s-]*squar(?:e|ed)|chi2|x\s*\^?\s*2)\s*\(\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*"
    r"([+-]?\d+(?:\.\d+)?)"
    r"(?:[^p]{0,40}?p\s*[<=>]\s*([<>]?=?)\s*(0?\.\d+|1(?:\.0+)?))?",
    re.I,
)
_Z = re.compile(
    r"\bz\s*=\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:[^p]{0,40}?p\s*[<=>]\s*([<>]?=?)\s*(0?\.\d+|1(?:\.0+)?))?",
    re.I,
)
_MEAN_N = re.compile(
    r"\b(?:M|mean)\s*=\s*(\d+\.\d+)\b(?:[^N]{0,80}?\b(?:N|n)\s*=\s*(\d+)\b)?"
    r"|(?:\b(?:N|n)\s*=\s*(\d+)\b[^M]{0,80}?\b(?:M|mean)\s*=\s*(\d+\.\d+)\b)",
    re.I,
)
_P_NEAR = re.compile(r"\bp\s*[<=>]\s*([<>]?=?)\s*(0?\.\d+|1(?:\.0+)?)", re.I)
_N_OR_CI = re.compile(
    r"\b(?:n\s*=|N\s*=|95%\s*CI|CI\s*\[|Cohen|odds ratio|OR\s*=)\b",
    re.I,
)


@dataclass(frozen=True)
class StatHit:
    kind: str  # t | F | chi2 | z | grim | p_no_n
    quote: str
    reported_p: float | None
    computed_p: float | None
    consistent: bool
    detail: str
    mean: float | None = None
    n: int | None = None


def grim_possible(mean: float, n: int, decimals: int) -> bool:
    """True when ``mean`` can arise as a mean of ``n`` granular observations."""
    if n < 1 or decimals < 0:
        return False
    scale = 10 ** decimals
    reported = round(mean * scale)
    lo = math.floor(mean * n) - 2
    hi = math.ceil(mean * n) + 2
    for total in range(lo, hi + 1):
        if round(total / n * scale) == reported:
            return True
    return False


def decimals_of(text: str) -> int:
    if "." not in text:
        return 0
    frac = text.split(".", 1)[1]
    frac = re.sub(r"[^0-9].*", "", frac)
    return len(frac)


def _erfc(x: float) -> float:
    return math.erfc(x)


def z_two_tailed_p(z: float) -> float:
    return _erfc(abs(z) / math.sqrt(2.0))


def _log_gamma(z: float) -> float:
    # Lanczos approximation (g=7)
    p = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7,
    ]
    if z < 0.5:
        return math.log(math.pi / math.sin(math.pi * z)) - _log_gamma(1 - z)
    z -= 1
    x = p[0]
    for i, pi in enumerate(p[1:], start=1):
        x += pi / (z + i)
    t = z + 7.5
    return math.log(math.sqrt(2 * math.pi)) + (z + 0.5) * math.log(t) - t + math.log(x)


def _betacf(a: float, b: float, x: float) -> float:
    max_iter = 200
    eps = 3e-12
    fpmin = 1e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _reg_inc_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if a <= 0.0 or b <= 0.0:
        return float("nan")
    ln_beta = _log_gamma(a) + _log_gamma(b) - _log_gamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - ln_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_tailed_p(t: float, df: float) -> float:
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    # P(|T| > |t|) = incomplete beta
    return _reg_inc_beta(df / 2.0, 0.5, x)


def f_right_p(f: float, d1: float, d2: float) -> float:
    if f <= 0 or d1 <= 0 or d2 <= 0:
        return float("nan")
    return _reg_inc_beta(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


def _lower_gamma_reg(s: float, x: float) -> float:
    """Regularized lower incomplete gamma P(s,x). Series / continued fraction."""
    if x < 0 or s <= 0:
        return float("nan")
    if x == 0:
        return 0.0
    if x < s + 1:
        total = 1.0 / s
        term = total
        for n in range(1, 200):
            term *= x / (s + n)
            total += term
            if abs(term) < abs(total) * 1e-12:
                break
        return total * math.exp(-x + s * math.log(x) - _log_gamma(s))
    # continued fraction for Q, then 1-Q
    b0 = x + 1.0 - s
    c = 1e30
    d = 1.0 / b0
    h = d
    for i in range(1, 200):
        an = -i * (i - s)
        b0 += 2.0
        d = an * d + b0
        if abs(d) < 1e-30:
            d = 1e-30
        c = b0 + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    q = math.exp(-x + s * math.log(x) - _log_gamma(s)) * h
    return 1.0 - q


def chi2_right_p(stat: float, df: float) -> float:
    if stat < 0 or df <= 0:
        return float("nan")
    return 1.0 - _lower_gamma_reg(df / 2.0, stat / 2.0)


def _parse_p(op: str | None, raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _p_matches(reported: float, computed: float, *, decimals: int | None = None) -> bool:
    """statcheck-ish: allow rounding of the reported p."""
    if math.isnan(computed):
        return True
    if reported <= 0:
        return computed <= 0.0005
    # Infer decimals from the reported string via magnitude.
    if reported >= 0.1:
        tol = 0.05
    elif reported >= 0.01:
        tol = 0.005
    else:
        tol = 0.0005
    if decimals is not None:
        tol = 0.5 / (10 ** decimals) + 1e-12
    return abs(computed - reported) <= max(tol, abs(computed) * 0.05 + 1e-9)


def scan_stats(text: str) -> list[StatHit]:
    hits: list[StatHit] = []
    for m in _T.finditer(text):
        df = float(m.group(1))
        t = float(m.group(2))
        reported = _parse_p(m.group(3), m.group(4))
        computed = t_two_tailed_p(t, df)
        quote = m.group(0)[:200]
        ok = reported is None or _p_matches(reported, computed)
        hits.append(
            StatHit(
                kind="t",
                quote=quote,
                reported_p=reported,
                computed_p=computed,
                consistent=ok,
                detail=(
                    f"t({df:g})={t:g} → p≈{computed:.4g}"
                    + ("" if reported is None else f" (reported {reported:g})")
                ),
            )
        )
    for m in _F.finditer(text):
        d1, d2, fval = float(m.group(1)), float(m.group(2)), float(m.group(3))
        reported = _parse_p(m.group(4), m.group(5))
        computed = f_right_p(fval, d1, d2)
        quote = m.group(0)[:200]
        ok = reported is None or _p_matches(reported, computed)
        hits.append(
            StatHit(
                kind="F",
                quote=quote,
                reported_p=reported,
                computed_p=computed,
                consistent=ok,
                detail=(
                    f"F({d1:g},{d2:g})={fval:g} → p≈{computed:.4g}"
                    + ("" if reported is None else f" (reported {reported:g})")
                ),
            )
        )
    for m in _CHI.finditer(text):
        df, stat = float(m.group(1)), float(m.group(2))
        reported = _parse_p(m.group(3), m.group(4))
        computed = chi2_right_p(stat, df)
        quote = m.group(0)[:200]
        ok = reported is None or _p_matches(reported, computed)
        hits.append(
            StatHit(
                kind="chi2",
                quote=quote,
                reported_p=reported,
                computed_p=computed,
                consistent=ok,
                detail=(
                    f"χ²({df:g})={stat:g} → p≈{computed:.4g}"
                    + ("" if reported is None else f" (reported {reported:g})")
                ),
            )
        )
    for m in _Z.finditer(text):
        z = float(m.group(1))
        reported = _parse_p(m.group(2), m.group(3))
        computed = z_two_tailed_p(z)
        quote = m.group(0)[:200]
        ok = reported is None or _p_matches(reported, computed)
        hits.append(
            StatHit(
                kind="z",
                quote=quote,
                reported_p=reported,
                computed_p=computed,
                consistent=ok,
                detail=(
                    f"z={z:g} → p≈{computed:.4g}"
                    + ("" if reported is None else f" (reported {reported:g})")
                ),
            )
        )
    for m in _MEAN_N.finditer(text):
        if m.group(1) and m.group(2):
            mean_s, n_s = m.group(1), m.group(2)
        elif m.group(4) and m.group(3):
            mean_s, n_s = m.group(4), m.group(3)
        else:
            continue
        mean = float(mean_s)
        n = int(n_s)
        dec = decimals_of(mean_s)
        possible = grim_possible(mean, n, dec)
        hits.append(
            StatHit(
                kind="grim",
                quote=m.group(0)[:200],
                reported_p=None,
                computed_p=None,
                consistent=possible,
                detail=f"GRIM: M={mean_s}, N={n} ({'possible' if possible else 'impossible'})",
                mean=mean,
                n=n,
            )
        )
    for m in _P_NEAR.finditer(text):
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        window = text[start:end]
        if _N_OR_CI.search(window):
            continue
        # Skip p-values already attached to a test statistic we parsed.
        if any(h.quote and h.quote in window and h.kind in {"t", "F", "chi2", "z"} for h in hits):
            continue
        hits.append(
            StatHit(
                kind="p_no_n",
                quote=window.strip()[:200],
                reported_p=_parse_p(m.group(1), m.group(2)),
                computed_p=None,
                consistent=True,
                detail="p-value with no nearby n=, CI, or effect size",
            )
        )
    return hits
