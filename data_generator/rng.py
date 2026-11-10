"""Deterministic random number generators.

Every generator asks for its own ``random.Random`` keyed by the global seed plus a name
(and usually a date or an id). The same seed therefore always produces the same data, and
adding a day to a run never changes the draws made for earlier days.
"""

from __future__ import annotations

import hashlib
import math
import random


def rng_for(seed: int, *parts: object) -> random.Random:
    key = "|".join([str(seed), *map(str, parts)])
    digest = hashlib.sha256(key.encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def lognormal_minutes(rng: random.Random, mean: float, sigma: float = 0.45) -> float:
    """A right-skewed duration with the given mean, as handle times are in practice."""
    mu = math.log(mean) - sigma**2 / 2
    return rng.lognormvariate(mu, sigma)


def poisson_like(rng: random.Random, mean: float) -> int:
    """A count around ``mean`` with Poisson-like spread (normal approximation, never negative)."""
    if mean <= 0:
        return 0
    return max(0, round(rng.gauss(mean, math.sqrt(mean))))
