"""The random draws and the spike target (research R-15, R-16). Written before the implementation."""

import math
import random
import statistics

import pytest

from erp.errors import ErpError
from erp.services.sampling import binomial, poisson
from erp.services.simulate import SpikeNeedsHistory, baseline, spike_target


@pytest.mark.parametrize("lam", [4, 40])
def test_poisson_mean_is_within_5_percent_of_lambda(lam: int) -> None:
    rng = random.Random(12345)
    draws = [poisson(rng, lam) for _ in range(10_000)]
    assert abs(statistics.mean(draws) - lam) <= 0.05 * lam
    assert min(draws) >= 0


def test_poisson_of_zero_or_less_is_zero() -> None:
    rng = random.Random(1)
    assert poisson(rng, 0) == 0
    assert poisson(rng, -3) == 0


def test_binomial_stays_between_zero_and_n() -> None:
    rng = random.Random(7)
    draws = [binomial(rng, 50, 0.02) for _ in range(1000)]
    assert all(0 <= d <= 50 for d in draws)
    assert binomial(rng, 0, 0.5) == 0


def test_spike_target_is_mean_plus_z_sample_sd() -> None:
    values = [20, 22, 18, 25, 21, 19, 23, 20, 24, 22, 18, 21, 20, 26, 19, 22, 21, 23, 20, 18,
              24, 22, 21, 19, 25, 20, 23, 22]  # fmt: skip
    assert len(values) == 28
    expected = math.ceil(statistics.mean(values) + 4 * statistics.stdev(values))
    assert spike_target(values, 4) == expected
    assert spike_target(values, 3) < spike_target(values, 4)


def test_spike_target_with_equal_values_uses_sd_of_one() -> None:
    assert spike_target([10] * 28, 4) == 14  # ceil(10 + 4 x 1)


def test_spike_with_fewer_than_28_days_is_refused() -> None:
    with pytest.raises(SpikeNeedsHistory) as caught:
        spike_target([10] * 27, 4)
    assert isinstance(caught.value, ErpError)
    assert (caught.value.status_code, caught.value.code) == (422, "SPIKE_NEEDS_HISTORY")


def test_baseline_is_the_mean_with_a_minimum_of_one() -> None:
    assert baseline([10, 20]) == 15
    assert baseline([]) == 1
    assert baseline([0, 0, 0]) == 1
