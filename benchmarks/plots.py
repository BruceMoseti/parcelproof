"""Figures for results/figures/, drawn only from the committed CSVs.

This script never simulates or measures anything. If a figure disagrees with a table, the figure is
wrong, because the tables are the record.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results"
TABLES = RESULTS / "tables"
FIGURES = RESULTS / "figures"

PRIMARY_TIMEOUT = 3600.0


def read(name: str) -> list[dict]:
    with (TABLES / name).open() as handle:
        return list(csv.DictReader(handle))


def save(fig, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / name
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path.relative_to(RESULTS.parent)}")


def pareto_frontier(rows: list[dict]) -> list[dict]:
    """The configurations that are not beaten on both cost and latency at once."""
    ordered = sorted(rows, key=lambda row: float(row["latency_p95_s"]))
    best_cost = float("inf")
    frontier = []
    for row in ordered:
        cost = float(row["usd_per_10k_parcels_typical"])
        if cost < best_cost:
            frontier.append(row)
            best_cost = cost
    return frontier


def plot_frontier() -> None:
    """The headline figure: what a latency budget buys you.

    All 52 policies are shown, because the frontier only means something next to the options it
    dominates. Many coincide: a timeout that never fires leaves the policy identical to one with a
    longer timeout, so those points sit on top of each other.
    """
    rows = read("frontier.csv")
    comparison = read("strategy_comparison.csv")
    frontier = pareto_frontier(rows)

    fig, ax = plt.subplots(figsize=(9.5, 6))
    ax.scatter(
        [float(row["latency_p95_s"]) for row in rows],
        [float(row["usd_per_10k_parcels_typical"]) for row in rows],
        s=22,
        color="#8899aa",
        alpha=0.55,
        label=f"all {len(rows)} batch size / timeout policies",
    )
    ax.plot(
        [float(row["latency_p95_s"]) for row in frontier],
        [float(row["usd_per_10k_parcels_typical"]) for row in frontier],
        color="#2f6fb0",
        linewidth=2.0,
        marker="o",
        markersize=5,
        label="Pareto frontier",
    )

    for row in comparison:
        if row["strategy"] == "merkle_anchor":
            continue
        ax.scatter(
            float(row["latency_p95_s"]),
            float(row["usd_per_10k_parcels_typical"]),
            marker="X",
            s=150,
            zorder=5,
            label=f"{row['strategy'].replace('_', ' ')} (no batching)",
        )

    # A batch size can appear more than once on the frontier, under different timeouts, so label
    # only its first occurrence to keep the annotations from stacking.
    labelled: set[int] = set()
    for row in frontier:
        batch_size = int(row["batch_size"])
        if batch_size in (1, 8, 64, 512, 4096) and batch_size not in labelled:
            labelled.add(batch_size)
            ax.annotate(
                f"B={batch_size}",
                (float(row["latency_p95_s"]), float(row["usd_per_10k_parcels_typical"])),
                textcoords="offset points",
                xytext=(7, 7),
                fontsize=8,
            )

    ax.axvline(12.0, color="#444444", linestyle="--", linewidth=1.0)
    ax.annotate(
        "one block (12s):\nlatency floor",
        (12.0, min(float(row["usd_per_10k_parcels_typical"]) for row in rows) * 1.6),
        textcoords="offset points",
        xytext=(8, 0),
        fontsize=8,
        color="#444444",
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("p95 settlement latency (seconds, log scale)")
    ax.set_ylabel("USD per 10,000 parcels at 20 gwei (log scale)")
    ax.set_title("Cost of tamper-evident custody against settlement latency")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=8, loc="upper right")
    save(fig, "01_cost_latency_frontier.png")


def plot_gas_per_event() -> None:
    rows = read("strategy_comparison.csv")
    labels, values = [], []
    for row in rows:
        label = row["strategy"].replace("_", " ")
        if row["strategy"] == "merkle_anchor":
            label = f"merkle anchor\nB={row['batch_size']}"
        labels.append(label)
        values.append(float(row["gas_per_event"]))

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=["#b03030"] * 2 + ["#2f6fb0"] * (len(labels) - 2))
    ax.set_yscale("log")
    ax.set_ylabel("gas per custody event (log scale)")
    ax.set_title("Amortised gas per custody event by anchoring strategy")
    ax.grid(True, axis="y", which="both", alpha=0.25)
    for bar, value in zip(bars, values, strict=True):
        ax.annotate(
            f"{value:,.0f}" if value >= 10 else f"{value:,.1f}",
            (bar.get_x() + bar.get_width() / 2, value),
            textcoords="offset points",
            xytext=(0, 4),
            ha="center",
            fontsize=8,
        )
    save(fig, "02_gas_per_event_by_strategy.png")


def plot_verification_gas() -> None:
    rows = read("verification_gas.csv")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(
        [int(row["proof_len"]) for row in rows],
        [int(row["verify_gas"]) for row in rows],
        marker="o",
        color="#2f6fb0",
    )
    for row in rows:
        if int(row["batch_size"]) in (1, 256, 4096):
            ax.annotate(
                f"B={row['batch_size']}",
                (int(row["proof_len"]), int(row["verify_gas"])),
                textcoords="offset points",
                xytext=(6, -10),
                fontsize=8,
            )
    ax.set_xlabel("inclusion proof length (hashes)")
    ax.set_ylabel("gas to verify one proof on-chain")
    ax.set_title("Verification cost is the price of large batches")
    ax.grid(True, alpha=0.25)
    save(fig, "03_verification_gas_vs_proof_depth.png")


def plot_rate_sensitivity() -> None:
    rows = read("rate_sensitivity.csv")
    fig, ax = plt.subplots(figsize=(9, 5))
    for batch_size in sorted({int(row["batch_size"]) for row in rows}):
        series = [row for row in rows if int(row["batch_size"]) == batch_size]
        series.sort(key=lambda row: float(row["parcels_per_hour"]))
        ax.plot(
            [float(row["parcels_per_hour"]) for row in series],
            [float(row["usd_per_10k_parcels_typical"]) for row in series],
            marker="o",
            label=f"B={batch_size}",
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("parcel entry rate (parcels per hour, log scale)")
    ax.set_ylabel("USD per 10,000 parcels at 20 gwei (log scale)")
    ax.set_title("The same policy costs a small depot more than a large hub")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    save(fig, "04_cost_vs_throughput.png")


def main() -> None:
    plot_frontier()
    plot_gas_per_event()
    plot_verification_gas()
    plot_rate_sensitivity()


if __name__ == "__main__":
    main()
