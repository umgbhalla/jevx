"""CRAP-for-agents: algebraic risk over organic work.

Savoia's CRAP(m) = comp^2 * (1-cov)^3 + comp fused a deterministic structural
signal (complexity, counted by code) with a calibrated belief (coverage). Same
shape here: blast radius is counted by code, doubt comes from Jev.

    risk = blast**2 * (1 - confidence)**3 + blast

Safe-but-complex scores low, simple-but-doubtful scores high,
complex-and-doubtful explodes. Thresholds belong to the action's stakes.
"""

from __future__ import annotations


def risk(blast: float, confidence: float) -> float:
    """blast >= 0 counted by code; confidence 0..1 from Jev. Higher = riskier."""
    if blast < 0:
        raise ValueError("blast must be >= 0")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be within 0..1")
    return blast**2 * (1.0 - confidence) ** 3 + blast


def verdict(risk_value: float, *, review_at: float, refuse_at: float) -> str:
    """act | review | refuse. Calibrate review_at/refuse_at per action stakes."""
    if not review_at <= refuse_at:
        raise ValueError(f"need review_at <= refuse_at, got {review_at}, {refuse_at}")
    if risk_value >= refuse_at:
        return "refuse"
    if risk_value >= review_at:
        return "review"
    return "act"


def blast_of(*signals: float, cap: float = 5.0) -> float:
    """Blast radius from countable signals, each 0..1.

    Worst dominates, rest add a tail. Capped so one number
    can't nuke the scale — tune per domain.
    """
    import math as _m

    if not signals:
        return 0.0
    for s in signals:
        if not isinstance(s, (int, float)) or not _m.isfinite(s) or not 0.0 <= s <= 1.0:
            raise ValueError(f"blast signals must be 0..1 finite, got {s!r}")
    return max(0.0, min(cap, max(signals) + 0.25 * (sum(signals) - max(signals))))
