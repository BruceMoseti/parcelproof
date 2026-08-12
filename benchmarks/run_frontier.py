"""Cost and latency of anchoring a parcel network's custody events.

Combines the measured per-transaction gas from ``measure_gas.py`` with the anchoring policy
simulation in ``parcelproof.policy`` to answer the question the project exists to answer: given a
settlement latency budget, what is the cheapest way to make custody records tamper-evident?

Reads:  results/tables/gas_per_operation.csv
Writes: results/tables/trace_summary.csv
        results/tables/strategy_comparison.csv
        results/tables/frontier.csv
        results/tables/sla_optimal.csv
        results/tables/rate_sensitivity.csv
        results/tables/price_scenarios.csv

Two things are kept strictly apart. Gas is measured: every gas figure here traces back to a
transaction receipt on a real EVM. Prices are assumptions, and they are written out next to the
results so nobody has to guess which is which.
"""

from __future__ import annotations

import csv
from pathlib import Path

from parcelproof.cost import SCENARIOS
from parcelproof.policy import AnchorPolicy, simulate
from parcelproof.trace import events_per_parcel, poisson_arrivals

TABLES = Path(__file__).resolve().parents[1] / "results" / "tables"

SEED = 20260812

# Primary scenario: a regional operation entering 500 parcels an hour. The custody event rate is
# derived from the parcel lifecycle model rather than picked, so it stays consistent with the
# events-per-parcel figure published in trace_summary.csv.
PARCELS_PER_HOUR = 500.0
HORIZON_HOURS = 168.0

BATCH_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
TIMEOUTS_S = [60.0, 300.0, 900.0, 3600.0]

# Settlement latency budgets to price, spanning what a logistics integration might plausibly ask
# for: near real time, a few minutes, a quarter hour, an hour.
SLA_TARGETS_S = [60.0, 300.0, 900.0, 3600.0]

# Parcel entry rates for the sensitivity table: a small depot, the primary scenario, a large hub.
SENSITIVITY_PARCEL_RATES = [50.0, 500.0, 5000.0]

REFERENCE_PARCELS = 10_000


def read_gas() -> dict[str, float]:
    """Measured per-transaction gas, keyed by strategy."""
    path = TABLES / "gas_per_operation.csv"
    if not path.exists():
        raise SystemExit(f"{path} missing; run `python benchmarks/measure_gas.py` first")
    with path.open() as handle:
        rows = list(csv.DictReader(handle))

    gas = {}
    for row in rows:
        key = row["strategy"]
        if row["operation"].startswith("anchor - first"):
            key = "merkle_anchor_first"
        gas[key] = float(row["gas_mean"])
    return gas


def merkle_total_gas(anchors: int, gas: dict[str, float]) -> float:
    """Total gas to anchor a stream, charging the first call at its real higher rate."""
    return gas["merkle_anchor_first"] + (anchors - 1) * gas["merkle_anchor"]


def cost_columns(gas_per_event: float, per_parcel: float) -> dict[str, float]:
    """USD per 10,000 parcels under every price scenario, plus USD per event.

    Parcels are the unit a logistics operator thinks in, so gas per event is converted using the
    measured events-per-parcel figure rather than assumed to be one event per parcel.
    """
    gas_per_reference = gas_per_event * per_parcel * REFERENCE_PARCELS
    columns = {
        f"usd_per_10k_parcels_{scenario.name}": round(scenario.usd(gas_per_reference), 4)
        for scenario in SCENARIOS
    }
    typical = next(scenario for scenario in SCENARIOS if scenario.name == "typical")
    columns["usd_per_event_typical"] = round(typical.usd(gas_per_event), 8)
    return columns


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(path.parents[2])} ({len(rows)} rows)")


def build_frontier(
    arrivals: list[float], gas: dict[str, float], per_parcel: float
) -> list[dict]:
    rows = []
    for timeout_s in TIMEOUTS_S:
        for batch_size in BATCH_SIZES:
            outcome = simulate(arrivals, AnchorPolicy(batch_size, timeout_s))
            total_gas = merkle_total_gas(outcome.anchor_count, gas)
            gas_per_event = total_gas / outcome.event_count
            rows.append(
                {
                    "batch_size": batch_size,
                    "timeout_s": timeout_s,
                    "anchors": outcome.anchor_count,
                    "events_per_anchor": round(outcome.events_per_anchor, 3),
                    "timeout_flush_share": round(outcome.timeout_flush_share, 4),
                    "gas_total": round(total_gas, 1),
                    "gas_per_event": round(gas_per_event, 3),
                    "latency_p50_s": round(outcome.latency_percentile(50), 1),
                    "latency_p95_s": round(outcome.latency_percentile(95), 1),
                    "latency_p99_s": round(outcome.latency_percentile(99), 1),
                    "latency_max_s": round(max(outcome.latencies), 1),
                    # Gas per event times p95 latency. Not a canonical metric; it is here only
                    # because where it stops falling is where the tradeoff changes character.
                    # While block time dominates latency, doubling the batch nearly halves cost
                    # for almost no latency, and the product falls. Once batch fill time
                    # dominates, cost and latency trade off one for one and the product is flat.
                    "cost_latency_product": round(
                        gas_per_event * outcome.latency_percentile(95), 1
                    ),
                    **cost_columns(gas_per_event, per_parcel),
                }
            )
    return rows


def build_strategy_comparison(
    arrivals: list[float], gas: dict[str, float], per_parcel: float
) -> list[dict]:
    """The headline table: the two per-event strategies against batched anchoring.

    The per-event strategies send one transaction per custody event on arrival, so their settlement
    latency is exactly what a batch size of one produces: the wait for the next block and nothing
    else. That makes `B=1` the like-for-like latency comparison, and it is also where batching is at
    its worst, since anchoring a root that commits to a single event is pure overhead.
    """
    immediate = simulate(arrivals, AnchorPolicy(batch_size=1, timeout_s=60.0))
    event_count = immediate.event_count
    rows = []

    for strategy in ("per_event_storage", "per_event_log"):
        rows.append(
            {
                "strategy": strategy,
                "batch_size": 1,
                "transactions": event_count,
                "gas_per_event": round(gas[strategy], 3),
                "latency_p95_s": round(immediate.latency_percentile(95), 1),
                **cost_columns(gas[strategy], per_parcel),
            }
        )

    for batch_size in (1, 16, 256, 4096):
        outcome = simulate(arrivals, AnchorPolicy(batch_size, timeout_s=3600.0))
        gas_per_event = merkle_total_gas(outcome.anchor_count, gas) / outcome.event_count
        rows.append(
            {
                "strategy": "merkle_anchor",
                "batch_size": batch_size,
                "transactions": outcome.anchor_count,
                "gas_per_event": round(gas_per_event, 3),
                "latency_p95_s": round(outcome.latency_percentile(95), 1),
                **cost_columns(gas_per_event, per_parcel),
            }
        )
    return rows


def build_sla_optimal(frontier: list[dict]) -> list[dict]:
    """The cheapest policy that meets each settlement latency budget.

    This is the direct answer to the research question. The search runs over the same policy grid
    written to frontier.csv, so every row here can be checked against that table.
    """
    rows = []
    for target in SLA_TARGETS_S:
        feasible = [row for row in frontier if row["latency_p95_s"] <= target]
        if not feasible:
            continue
        best = min(feasible, key=lambda row: row["gas_per_event"])
        rows.append(
            {
                "sla_p95_s": target,
                "sla_p95_label": _duration(target),
                "batch_size": best["batch_size"],
                "timeout_s": best["timeout_s"],
                "anchors": best["anchors"],
                "events_per_anchor": best["events_per_anchor"],
                "gas_per_event": best["gas_per_event"],
                "latency_p50_s": best["latency_p50_s"],
                "latency_p95_s": best["latency_p95_s"],
                "usd_per_10k_parcels_typical": best["usd_per_10k_parcels_typical"],
            }
        )
    return rows


def build_rate_sensitivity(gas: dict[str, float], per_parcel: float) -> list[dict]:
    """How the frontier moves with throughput.

    A large batch is cheap because it spreads one transaction over many events, but it only fills
    quickly if events arrive quickly. At low volume the timeout does the flushing instead, so the
    realised batch is closer to `rate x timeout` than to the configured size, and cost per event
    rises even though the policy is unchanged. A design that is cheap for a national carrier can be
    ordinary for a single depot, and this table is where that shows.
    """
    rows = []
    for parcel_rate in SENSITIVITY_PARCEL_RATES:
        arrivals = poisson_arrivals(parcel_rate * per_parcel, HORIZON_HOURS, seed=SEED)
        for batch_size in (16, 256, 4096):
            outcome = simulate(arrivals, AnchorPolicy(batch_size, timeout_s=3600.0))
            gas_per_event = merkle_total_gas(outcome.anchor_count, gas) / outcome.event_count
            rows.append(
                {
                    "parcels_per_hour": parcel_rate,
                    "events_per_hour": round(parcel_rate * per_parcel, 1),
                    "batch_size": batch_size,
                    "events_per_anchor": round(outcome.events_per_anchor, 3),
                    "timeout_flush_share": round(outcome.timeout_flush_share, 4),
                    "gas_per_event": round(gas_per_event, 3),
                    "latency_p50_s": round(outcome.latency_percentile(50), 1),
                    "latency_p95_s": round(outcome.latency_percentile(95), 1),
                    "usd_per_10k_parcels_typical": cost_columns(gas_per_event, per_parcel)[
                        "usd_per_10k_parcels_typical"
                    ],
                }
            )
    return rows


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:g}s"
    if seconds < 3600:
        return f"{seconds / 60:g} min"
    return f"{seconds / 3600:g} h"


def main() -> None:
    per_parcel = events_per_parcel(seed=SEED)
    events_per_hour = PARCELS_PER_HOUR * per_parcel
    arrivals = poisson_arrivals(events_per_hour, HORIZON_HOURS, seed=SEED)
    print(
        f"{len(arrivals)} custody events over {HORIZON_HOURS:g}h "
        f"at {events_per_hour:.1f} events/hour ({per_parcel:.4f} events per parcel)"
    )

    gas = read_gas()

    write_csv(
        TABLES / "trace_summary.csv",
        [
            {
                "parcels_modelled": 10_000,
                "events_per_parcel": round(per_parcel, 4),
                "parcels_per_hour": PARCELS_PER_HOUR,
                "events_per_hour": round(events_per_hour, 1),
                "sweep_horizon_hours": HORIZON_HOURS,
                "sweep_events": len(arrivals),
                "seed": SEED,
            }
        ],
    )
    write_csv(
        TABLES / "price_scenarios.csv",
        [
            {
                "name": scenario.name,
                "gas_price_gwei": scenario.gas_price_gwei,
                "eth_price_usd": scenario.eth_price_usd,
                "note": "assumption - not a measurement",
            }
            for scenario in SCENARIOS
        ],
    )

    frontier = build_frontier(arrivals, gas, per_parcel)
    write_csv(TABLES / "frontier.csv", frontier)
    write_csv(
        TABLES / "strategy_comparison.csv",
        build_strategy_comparison(arrivals, gas, per_parcel),
    )
    write_csv(TABLES / "sla_optimal.csv", build_sla_optimal(frontier))
    write_csv(TABLES / "rate_sensitivity.csv", build_rate_sensitivity(gas, per_parcel))


if __name__ == "__main__":
    main()
