"""Synthetic parcel network trace.

The benchmark needs an event stream with a realistic shape: parcels entering the network at
random times, each producing a handful of custody events spread over hours or days. The numbers
below are a stated model, not measurements from a real carrier, and the README says so. What
matters for the cost result is the *arrival process* into the anchoring queue, which is the
superposition of many parcel timelines, and that shape is reproduced faithfully by a Poisson
entry process with heavy tailed dwell times.

Everything is driven by a seeded ``random.Random``, so a given seed always produces byte
identical events.
"""

from __future__ import annotations

import random

from .events import CustodyEvent, EventType

HUBS = (
    "EWR-01",
    "MEM-02",
    "ONT-03",
    "DFW-04",
    "ATL-05",
    "ORD-06",
    "CVG-07",
    "PHX-08",
)
CARRIERS = ("carrier-north", "carrier-south", "carrier-air")

# Lognormal dwell and transit times, in hours, chosen so medians land on plausible values:
# about 3.3h sorting at a facility, 8.2h between facilities, 5.5h on the delivery van.
_FACILITY_DWELL = (1.2, 0.6)
_LINE_HAUL = (2.1, 0.5)
_LAST_MILE = (1.7, 0.4)

EXCEPTION_RATE = 0.04


def _hours(rng: random.Random, params: tuple[float, float]) -> float:
    mu, sigma = params
    return rng.lognormvariate(mu, sigma)


def parcel_events(
    rng: random.Random, parcel_id: str, entered_at: float
) -> list[CustodyEvent]:
    """One parcel's chain of custody, from pickup to delivery."""
    origin, *rest = rng.sample(HUBS, rng.randint(3, 5))
    destination = rest[-1]
    intermediate = rest[:-1]
    carrier = rng.choice(CARRIERS)

    now = entered_at
    sequence = 0
    events = [
        CustodyEvent(parcel_id, sequence, EventType.PICKUP, carrier, origin, round(now))
    ]

    for hub in [*intermediate, destination]:
        now += _hours(rng, _LINE_HAUL) * 3600
        sequence += 1
        events.append(
            CustodyEvent(parcel_id, sequence, EventType.ARRIVE_FACILITY, carrier, hub, round(now))
        )

        if rng.random() < EXCEPTION_RATE:
            now += _hours(rng, _FACILITY_DWELL) * 3600
            sequence += 1
            events.append(
                CustodyEvent(parcel_id, sequence, EventType.EXCEPTION, carrier, hub, round(now))
            )

        if hub != destination:
            now += _hours(rng, _FACILITY_DWELL) * 3600
            sequence += 1
            events.append(
                CustodyEvent(
                    parcel_id, sequence, EventType.DEPART_FACILITY, carrier, hub, round(now)
                )
            )

    now += _hours(rng, _FACILITY_DWELL) * 3600
    sequence += 1
    events.append(
        CustodyEvent(
            parcel_id, sequence, EventType.OUT_FOR_DELIVERY, carrier, destination, round(now)
        )
    )

    now += _hours(rng, _LAST_MILE) * 3600
    sequence += 1
    events.append(
        CustodyEvent(parcel_id, sequence, EventType.DELIVERED, carrier, destination, round(now))
    )
    return events


def generate(parcels: int, parcels_per_hour: float, seed: int = 20260812) -> list[CustodyEvent]:
    """Generate a trace of `parcels` shipments, sorted by the time each event occurred.

    Parcels enter the network as a Poisson process at `parcels_per_hour`, so inter-entry gaps are
    exponential. The returned order is the order an ingest endpoint would see the events, which is
    what the anchoring policy batches over.
    """
    if parcels <= 0:
        raise ValueError("parcels must be positive")
    if parcels_per_hour <= 0:
        raise ValueError("parcels_per_hour must be positive")

    rng = random.Random(seed)
    mean_gap = 3600.0 / parcels_per_hour
    events: list[CustodyEvent] = []
    entered_at = 0.0
    for index in range(parcels):
        entered_at += rng.expovariate(1.0 / mean_gap)
        events.extend(parcel_events(rng, f"PP{index:07d}", entered_at))

    # Sort by occurrence, then by parcel and sequence so ties are broken deterministically.
    events.sort(key=lambda event: (event.occurred_at, event.parcel_id, event.sequence))
    return events


def arrival_times(events: list[CustodyEvent]) -> list[float]:
    """The ingest arrival stream the anchoring policy sees, in seconds."""
    return [float(event.occurred_at) for event in events]
