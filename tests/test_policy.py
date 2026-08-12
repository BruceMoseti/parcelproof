import math

import pytest

from parcelproof.policy import AnchorPolicy, simulate
from parcelproof.trace import arrival_times, generate


def test_batch_size_one_anchors_every_event():
    outcome = simulate([0.0, 1.0, 2.0], AnchorPolicy(batch_size=1, timeout_s=60))
    assert outcome.anchor_count == 3
    assert outcome.batch_sizes == [1, 1, 1]


def test_latency_is_only_the_wait_for_the_next_block_when_batching_is_off():
    """With B=1 an event is anchored on arrival, so all that remains is block inclusion."""
    outcome = simulate([0.0, 5.0, 12.0], AnchorPolicy(batch_size=1, timeout_s=60), slot_seconds=12)
    assert outcome.latencies == [0.0, 7.0, 0.0]


def test_full_batch_flushes_on_the_arrival_that_fills_it():
    outcome = simulate(
        [0.0, 1.0, 2.0, 3.0], AnchorPolicy(batch_size=4, timeout_s=1000), slot_seconds=12
    )
    assert outcome.anchor_count == 1
    # Submitted at t=3, included at the t=12 boundary, so the first event waited the longest.
    assert outcome.latencies == [12.0, 11.0, 10.0, 9.0]


def test_timeout_flushes_a_short_batch():
    outcome = simulate(
        [0.0, 1.0, 500.0], AnchorPolicy(batch_size=10, timeout_s=60), slot_seconds=12
    )
    assert outcome.batch_sizes == [2, 1]
    assert outcome.timeout_flush_share == 1.0


def test_timeout_bounds_latency_regardless_of_batch_size():
    """The property that makes large batches usable: a quiet period cannot strand an event."""
    arrivals = [0.0, 1.0]
    timeout = 60.0
    outcome = simulate(arrivals, AnchorPolicy(batch_size=100_000, timeout_s=timeout))
    assert max(outcome.latencies) <= timeout + 12.0


def test_events_per_anchor_never_exceeds_batch_size():
    arrivals = arrival_times(generate(parcels=200, parcels_per_hour=30, seed=1))
    for batch_size in (1, 8, 64, 512):
        outcome = simulate(arrivals, AnchorPolicy(batch_size=batch_size, timeout_s=600))
        assert outcome.events_per_anchor <= batch_size
        assert sum(outcome.batch_sizes) == outcome.event_count


def test_every_event_gets_exactly_one_latency():
    arrivals = arrival_times(generate(parcels=100, parcels_per_hour=20, seed=2))
    outcome = simulate(arrivals, AnchorPolicy(batch_size=32, timeout_s=300))
    assert len(outcome.latencies) == len(arrivals) == outcome.event_count


def test_latency_is_never_negative():
    arrivals = arrival_times(generate(parcels=100, parcels_per_hour=20, seed=3))
    outcome = simulate(arrivals, AnchorPolicy(batch_size=16, timeout_s=300))
    assert min(outcome.latencies) >= 0.0


def test_larger_batches_cost_more_latency_and_fewer_anchors():
    """The tradeoff the benchmark quantifies, asserted here as a direction so a regression in the
    model shows up as a test failure rather than a surprising figure."""
    arrivals = arrival_times(generate(parcels=400, parcels_per_hour=50, seed=4))
    small = simulate(arrivals, AnchorPolicy(batch_size=8, timeout_s=3600))
    large = simulate(arrivals, AnchorPolicy(batch_size=256, timeout_s=3600))

    assert large.anchor_count < small.anchor_count
    assert large.latency_percentile(95) > small.latency_percentile(95)


def test_percentiles_use_nearest_rank():
    outcome = simulate(list(range(0, 100)), AnchorPolicy(batch_size=1, timeout_s=10))
    ordered = sorted(outcome.latencies)
    for p in (50, 95, 99, 100):
        assert outcome.latency_percentile(p) == ordered[math.ceil(p / 100 * 100) - 1]


def test_percentile_bounds_are_validated():
    outcome = simulate([0.0], AnchorPolicy(batch_size=1, timeout_s=10))
    for bad in (0, -1, 101):
        with pytest.raises(ValueError, match="p must be"):
            outcome.latency_percentile(bad)


def test_invalid_policies_are_rejected():
    with pytest.raises(ValueError, match="batch_size"):
        AnchorPolicy(batch_size=0, timeout_s=10)
    with pytest.raises(ValueError, match="timeout_s"):
        AnchorPolicy(batch_size=1, timeout_s=0)


def test_empty_arrival_stream_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        simulate([], AnchorPolicy(batch_size=1, timeout_s=10))
