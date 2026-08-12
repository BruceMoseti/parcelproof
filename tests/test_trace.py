import pytest

from parcelproof.events import EventType
from parcelproof.trace import arrival_times, generate


def test_trace_is_reproducible_from_the_seed():
    assert generate(parcels=50, parcels_per_hour=25, seed=7) == generate(
        parcels=50, parcels_per_hour=25, seed=7
    )


def test_different_seeds_give_different_traces():
    assert generate(parcels=50, parcels_per_hour=25, seed=7) != generate(
        parcels=50, parcels_per_hour=25, seed=8
    )


def test_events_are_sorted_by_occurrence():
    events = generate(parcels=200, parcels_per_hour=40, seed=9)
    assert arrival_times(events) == sorted(arrival_times(events))


def test_every_parcel_starts_with_pickup_and_ends_delivered():
    events = generate(parcels=100, parcels_per_hour=30, seed=10)
    by_parcel: dict[str, list] = {}
    for event in events:
        by_parcel.setdefault(event.parcel_id, []).append(event)

    assert len(by_parcel) == 100
    for history in by_parcel.values():
        history.sort(key=lambda event: event.sequence)
        assert history[0].event_type is EventType.PICKUP
        assert history[-1].event_type is EventType.DELIVERED


def test_sequence_numbers_are_contiguous_within_a_parcel():
    events = generate(parcels=100, parcels_per_hour=30, seed=11)
    by_parcel: dict[str, list[int]] = {}
    for event in events:
        by_parcel.setdefault(event.parcel_id, []).append(event.sequence)
    for sequences in by_parcel.values():
        assert sorted(sequences) == list(range(len(sequences)))


def test_custody_timestamps_advance_within_a_parcel():
    events = generate(parcels=100, parcels_per_hour=30, seed=12)
    by_parcel: dict[str, list] = {}
    for event in events:
        by_parcel.setdefault(event.parcel_id, []).append(event)
    for history in by_parcel.values():
        history.sort(key=lambda event: event.sequence)
        times = [event.occurred_at for event in history]
        assert times == sorted(times)


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError, match="parcels must be positive"):
        generate(parcels=0, parcels_per_hour=10)
    with pytest.raises(ValueError, match="parcels_per_hour"):
        generate(parcels=10, parcels_per_hour=0)
