"""Measure what each anchoring strategy costs on a real EVM.

Writes two tables:

* ``results/tables/gas_per_operation.csv`` — the cost of a single transaction under each strategy.
* ``results/tables/verification_gas.csv`` — the cost of checking one inclusion proof on-chain,
  as a function of batch size.

Gas comes from transaction receipts against a local Anvil node, so it includes the 21,000 gas
intrinsic transaction cost and the cost of calldata. Both terms are central to the result and both
are invisible if you measure only the internal call, as `forge test --gas-report` does.

The only source of run-to-run variation is the EIP-2028 calldata discount: a zero byte costs 4 gas
and a non-zero byte costs 16, and event hashes contain a random number of zero bytes. The sample is
drawn from the seeded trace, so even that is reproducible, and both the raw spread and the
discount-normalised figure are recorded.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

from parcelproof import merkle
from parcelproof.chain import HARDFORK, Chain, local_node
from parcelproof.events import leaf_hash
from parcelproof.trace import generate

TABLES = Path(__file__).resolve().parents[1] / "results" / "tables"

# Sample size for each per-transaction measurement. The code path is fixed, so this only has to be
# large enough to characterise the calldata discount spread, not to average out real noise.
SAMPLES = 32

# Powers of two spanning one event per anchor up to a batch that takes hours to fill.
BATCH_SIZES = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]

# What each strategy can still prove once the events are on-chain. Recorded alongside cost because
# the cheapest option is not comparable to the others on capability.
ON_CHAIN_READABLE = {
    "per_event_storage": "yes - one slot per event",
    "per_event_log": "no - contracts cannot read logs",
    "merkle_anchor": "yes - via an inclusion proof",
}


def sample_leaves(count: int) -> list[bytes]:
    """Leaf hashes taken from the seeded trace rather than from invented bytes.

    Using real leaves means the measured calldata discount reflects the hashes this system would
    actually anchor.
    """
    events = generate(parcels=count, parcels_per_hour=500, seed=20260812)
    return [leaf_hash(event) for event in events[:count]]


def measure_per_event(
    chain: Chain, contract_name: str, strategy: str, leaves: list[bytes]
) -> dict:
    contract = chain.deploy(contract_name)
    receipts = [chain.send(contract.functions.record(leaf)) for leaf in leaves]
    return summarise(strategy, "record", receipts)


def measure_anchor(chain: Chain, leaves: list[bytes]) -> tuple[dict, dict]:
    """Anchoring cost, separating the one-off first call from the steady state.

    The first anchor initialises the batch counter from zero, which the EVM charges as a
    zero-to-non-zero storage write. Every later anchor updates a non-zero slot for a fraction of
    that. Reporting the first call as if it were typical would overstate the cost of the strategy.
    """
    contract = chain.deploy("MerkleAnchor")
    receipts = [
        chain.send(contract.functions.anchor(merkle.root([leaf]), 1)) for leaf in leaves
    ]
    first = summarise("merkle_anchor", "anchor - first call initialises counter", receipts[:1])
    steady = summarise("merkle_anchor", "anchor", receipts[1:])
    return first, steady


def summarise(strategy: str, operation: str, receipts: list) -> dict:
    raw = [receipt.gas_used for receipt in receipts]
    normalised = {receipt.gas_at_uniform_calldata for receipt in receipts}
    return {
        "strategy": strategy,
        "operation": operation,
        "samples": len(receipts),
        "gas_mean": round(statistics.fmean(raw), 3),
        "gas_min": min(raw),
        "gas_max": max(raw),
        "gas_spread_pct": round(100 * (max(raw) - min(raw)) / statistics.fmean(raw), 4),
        "gas_uniform_calldata": sorted(normalised)[0] if len(normalised) == 1 else "varies",
        "calldata_bytes": receipts[0].calldata_bytes,
        "on_chain_readable": ON_CHAIN_READABLE[strategy],
    }


def measure_verification(chain: Chain) -> list[dict]:
    """Cost of verifying one inclusion proof on-chain, per batch size.

    `verify` is a view function, so a normal read costs nothing. It is called here in a real
    transaction to get a receipt, which is why these figures include the 21,000 gas intrinsic cost
    and the calldata for the proof itself.
    """
    contract = chain.deploy("MerkleAnchor")
    rows = []
    for batch_size in BATCH_SIZES:
        leaves = sample_leaves(batch_size)
        chain.send(contract.functions.anchor(merkle.root(leaves), batch_size))
        batch_id = contract.functions.batchCount().call() - 1
        path = merkle.proof(leaves, 0)
        receipt = chain.send(contract.functions.verify(batch_id, leaves[0], path))
        rows.append(
            {
                "batch_size": batch_size,
                "proof_len": len(path),
                "proof_bytes": 32 * len(path),
                "verify_gas": receipt.gas_used,
                "verify_gas_uniform_calldata": receipt.gas_at_uniform_calldata,
                "calldata_bytes": receipt.calldata_bytes,
            }
        )
    return rows


def measure_hardfork_sensitivity() -> list[dict]:
    """The same operations under different EVM hardforks.

    Justifies pinning the hardfork rather than accepting Anvil's `latest` default. It also isolates
    where the EIP-7623 calldata floor introduced in Prague actually bites: transactions with small
    arguments are unaffected, while verifying a deep inclusion proof sends hundreds of bytes of
    calldata and does comparatively little work, so the floor sets its price.
    """
    leaves = sample_leaves(2)
    deep = sample_leaves(4096)
    rows = []
    for hardfork in ("shanghai", "cancun", "prague", "osaka"):
        with local_node(hardfork=hardfork) as chain:
            storage = chain.deploy("PerEventStorage")
            record_gas = chain.send(storage.functions.record(leaves[0])).gas_used

            contract = chain.deploy("MerkleAnchor")
            chain.send(contract.functions.anchor(merkle.root(leaves), 2))
            anchor_gas = chain.send(contract.functions.anchor(merkle.root(leaves), 2)).gas_used

            chain.send(contract.functions.anchor(merkle.root(deep), len(deep)))
            batch_id = contract.functions.batchCount().call() - 1
            verify_gas = chain.send(
                contract.functions.verify(batch_id, deep[0], merkle.proof(deep, 0))
            ).gas_used

        rows.append(
            {
                "hardfork": hardfork,
                "record_gas": record_gas,
                "anchor_gas": anchor_gas,
                "verify_gas_batch_4096": verify_gas,
                "verify_calldata_bytes": 32 * 12 + 132,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(path.parents[2])} ({len(rows)} rows)")


def main() -> None:
    leaves = sample_leaves(SAMPLES)
    with local_node() as chain:
        print(f"measuring per-transaction gas over {SAMPLES} samples on hardfork {HARDFORK}")
        storage = measure_per_event(chain, "PerEventStorage", "per_event_storage", leaves)
        logging = measure_per_event(chain, "PerEventLog", "per_event_log", leaves)
        first_anchor, steady_anchor = measure_anchor(chain, leaves)
        print(f"measuring on-chain verification gas for {len(BATCH_SIZES)} batch sizes")
        verification = measure_verification(chain)

    print("measuring the same operations across hardforks")
    hardforks = measure_hardfork_sensitivity()

    write_csv(
        TABLES / "gas_per_operation.csv",
        [storage, logging, first_anchor, steady_anchor],
    )
    write_csv(TABLES / "verification_gas.csv", verification)
    write_csv(TABLES / "hardfork_sensitivity.csv", hardforks)


if __name__ == "__main__":
    main()
