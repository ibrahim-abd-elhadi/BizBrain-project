"""Random draws built on the standard library only (research R-15): no numeric dependency.

Used by the seed history and by Simulate Sales. Every function takes the random.Random to draw
from, so a fixed seed gives repeatable numbers.
"""

import math
import random


def poisson(rng: random.Random, lam: float) -> int:
    """A Poisson draw. Knuth's method for small means, a normal approximation for large ones."""
    if lam <= 0:
        return 0
    if lam < 30:
        limit = math.exp(-lam)
        k = 0
        p = rng.random()
        while p > limit:
            k += 1
            p *= rng.random()
        return k
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def binomial(rng: random.Random, n: int, p: float) -> int:
    """How many of n units come back, each with probability p."""
    if n <= 0 or p <= 0:
        return 0
    return int(rng.binomialvariate(n, p))
