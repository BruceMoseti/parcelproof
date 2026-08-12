"""End-to-end walkthrough: ingest, anchor, prove, tamper, detect.

Run with `make demo`. Starts a throwaway EVM node, so it needs no network access, no funded
account, and no configuration.
"""

from __future__ import annotations

import random

from . import merkle
from .chain import local_node
from .events import leaf_hash
from .ledger import Ledger
from .trace import parcel_events

PARCELS = 24
SEED = 20260812


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> None:
    rng = random.Random(SEED)
    events = []
    for index in range(PARCELS):
        events.extend(parcel_events(rng, f"PP{index:07d}", entered_at=index * 900.0))
    events.sort(key=lambda event: (event.occurred_at, event.parcel_id, event.sequence))

    with Ledger() as ledger, local_node() as chain:
        rule("1. Ingest custody events")
        ledger.append_many(events)
        print(f"{len(events)} events from {PARCELS} parcels are pending")

        rule("2. Seal a batch and anchor its root on-chain")
        batch = ledger.seal_batch(sealed_at=int(events[-1].occurred_at))
        assert batch is not None
        anchor = chain.deploy("MerkleAnchor")
        receipt = chain.send(anchor.functions.anchor(batch.root, batch.leaf_count))
        chain_batch_id = anchor.functions.batchCount().call() - 1
        ledger.record_anchor(batch.id, chain_batch_id, receipt.tx_hash)

        print(f"root        0x{batch.root.hex()}")
        print(f"leaves      {batch.leaf_count} custody events committed by 32 bytes on-chain")
        print(f"gas         {receipt.gas_used:,} for the whole batch")
        print(f"per event   {receipt.gas_used / batch.leaf_count:,.1f} gas")

        rule("3. One parcel's chain of custody")
        parcel_id = events[0].parcel_id
        history = ledger.parcel_history(parcel_id)
        for event_id, event in history:
            print(
                f"  #{event_id:<4} seq {event.sequence}  "
                f"{event.event_type.value:<17} {event.location:<7} t={event.occurred_at}"
            )

        target_id, target = history[len(history) // 2]
        rule(f"4. Prove event #{target_id} is in the anchored batch")
        proof = ledger.inclusion_proof(target_id)
        print(f"proof       {len(proof.path)} hashes, {32 * len(proof.path)} bytes")
        print(f"off-chain   {_verdict(_verify_off_chain(proof))}")
        print(f"on-chain    {_verdict(_verify_on_chain(anchor, chain_batch_id, proof))}")

        rule("5. Tamper with the record, as a database operator could")
        original = target.location
        ledger.raw_update(target_id, location="PHX-08")
        print(f"location    {original} -> {ledger.event(target_id).location}")
        print("the row is edited and the database is internally consistent")

        tampered = ledger.inclusion_proof(target_id)
        print(f"off-chain   {_verdict(_verify_off_chain(tampered))}")
        print(f"on-chain    {_verdict(_verify_on_chain(anchor, chain_batch_id, tampered))}")

        rule("6. Restore the record")
        ledger.raw_update(target_id, location=original)
        restored = ledger.inclusion_proof(target_id)
        print(f"on-chain    {_verdict(_verify_on_chain(anchor, chain_batch_id, restored))}")

        print(
            "\nThe edit was detected by the contract, not by the database that was edited."
            "\nThat is the whole point: the 32 bytes on-chain outrank anyone's write access."
        )


def _verify_off_chain(proof) -> bool:
    """Recompute the leaf from the record as it stands now, then fold the proof over it."""
    return merkle.verify(leaf_hash(proof.event), proof.path, proof.root)


def _verify_on_chain(anchor, chain_batch_id: int, proof) -> bool:
    return anchor.functions.verify(
        chain_batch_id, leaf_hash(proof.event), proof.path
    ).call()


def _verdict(ok: bool) -> str:
    return "VERIFIED" if ok else "REJECTED - record does not match the anchored root"


if __name__ == "__main__":
    main()
