"""Anchoring policy and the settlement latency it produces.

A policy is a pair: anchor as soon as `batch_size` events are pending, or when the oldest pending
event has waited `timeout_s`, whichever comes first. The timeout is what stops a quiet period from
leaving events unanchored indefinitely, and it is why large batches do not imply unbounded latency.

Settlement latency for an event is the time from its arrival to the anchoring transaction being
included in a block. Block inclusion is modelled as the next slot boundary on a fixed 12 second
schedule, matching Ethereum's post-Merge slot time. Waiting for finality instead of inclusion adds
roughly two epochs to *every* configuration equally, so it shifts the whole curve without changing
which policy sits on the frontier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SLOT_SECONDS = 12.0


@dataclass(frozen=True)
class AnchorPolicy:
    batch_size: int
    timeout_s: float

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

    @property
    def label(self) -> str:
        return f"B={self.batch_size}, T={self.timeout_s:g}s"


@dataclass(frozen=True)
class Outcome:
    """What a policy did over one arrival stream."""

    policy: AnchorPolicy
    event_count: int
    anchor_count: int
    latencies: list[float]
    batch_sizes: list[int]

    @property
    def events_per_anchor(self) -> float:
        """Realised batch occupancy, which is below `batch_size` whenever the timeout fires."""
        return self.event_count / self.anchor_count

    @property
    def timeout_flush_share(self) -> float:
        full = sum(1 for size in self.batch_sizes if size == self.policy.batch_size)
        return (self.anchor_count - full) / self.anchor_count

    def latency_percentile(self, p: float) -> float:
        """Nearest rank percentile, so results are exact and implementation independent.

        Interpolating percentile definitions differ between libraries, which would make the
        published numbers depend on which one happened to be installed.
        """
        if not 0 < p <= 100:
            raise ValueError("p must be in (0, 100]")
        ordered = sorted(self.latencies)
        rank = math.ceil(p / 100 * len(ordered))
        return ordered[rank - 1]

    @property
    def mean_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies)


def _included_at(submitted_at: float, slot_seconds: float) -> float:
    """The next slot boundary at or after `submitted_at`."""
    return math.ceil(submitted_at / slot_seconds) * slot_seconds


def simulate(
    arrivals: list[float],
    policy: AnchorPolicy,
    slot_seconds: float = SLOT_SECONDS,
) -> Outcome:
    """Run `policy` over an arrival stream and record per event settlement latency.

    `arrivals` must be non-decreasing; `trace.arrival_times` guarantees that.
    """
    if not arrivals:
        raise ValueError("arrivals must not be empty")

    latencies: list[float] = []
    batch_sizes: list[int] = []
    pending: list[float] = []

    def flush(submitted_at: float) -> None:
        included_at = _included_at(submitted_at, slot_seconds)
        latencies.extend(included_at - arrival for arrival in pending)
        batch_sizes.append(len(pending))
        pending.clear()

    for arrival in arrivals:
        # A batch can only ever be short of `batch_size` here, because reaching it flushes
        # immediately below. So a timeout always flushes everything pending.
        if pending and pending[0] + policy.timeout_s <= arrival:
            flush(pending[0] + policy.timeout_s)
        pending.append(arrival)
        if len(pending) == policy.batch_size:
            flush(arrival)
    if pending:
        flush(pending[0] + policy.timeout_s)

    return Outcome(
        policy=policy,
        event_count=len(arrivals),
        anchor_count=len(batch_sizes),
        latencies=latencies,
        batch_sizes=batch_sizes,
    )
