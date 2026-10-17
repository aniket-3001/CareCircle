"""Pure, deterministic maths for Care Circle. No I/O, no graph, no LLM. Every constant is an assumption and is labelled as one.

Doses are never computed or advised here; this module only combines flags and ages.
"""
from __future__ import annotations

import math

# Assumption (not a clinical standard): relative weight of each DDInter severity label in the combined regimen risk.
SEVERITY_WEIGHT = {"minor": 0.1, "moderate": 0.3, "major": 0.7}
# FDA classes for enzyme-mediated flags (strong inhibitors raise exposure >=5-fold, moderate >=2-fold): same scale, assumption.
ENZYME_WEIGHT = {"strong": 0.7, "moderate": 0.3, "in vitro": 0.1}      # "in vitro" = seen in a laboratory, not shown in people: the lowest weight
# Carer belief decay: assumption, shown in the UI.
HALF_LIFE_HOURS = 72.0


def regimen_risk(weights: list[float]) -> float:
    """Noisy-OR over independent conflict weights: R = 1 - prod(1 - w). Not a probability of harm; a ranking aid."""
    r = 1.0
    for w in weights:
        r *= 1.0 - min(max(w, 0.0), 1.0)
    return round(1.0 - r, 4)


def decay(age_hours: float, half_life: float = HALF_LIFE_HOURS) -> float:
    """Exponential staleness: 1 at age 0, 0.5 at one half-life."""
    return math.exp(-math.log(2) * max(age_hours, 0.0) / half_life)


def divergence(unacked_item_weights: list[float], age_hours_each: list[float], half_life: float = HALF_LIFE_HOURS) -> float:
    """How far a carer's picture is from the record: risk weights of changes they have not acknowledged, each weighted by how
    long ago the change was made (older unacknowledged change = more worrying), summed with noisy-OR so it stays in [0,1]."""
    parts = []
    for w, age in zip(unacked_item_weights, age_hours_each):
        parts.append(min(max(w, 0.0), 1.0) * (1.0 - decay(age, half_life)) + min(max(w, 0.0), 1.0) * 0.25)
    return regimen_risk([min(p, 1.0) for p in parts])


def severity_weight(level: str) -> float | None:
    """None for 'unknown': an unrated pair is shown as unrated, never counted as safe or as risky."""
    return SEVERITY_WEIGHT.get((level or "").strip().lower())
