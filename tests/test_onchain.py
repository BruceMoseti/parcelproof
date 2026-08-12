"""Cross-language checks against a real EVM.

The Python tree in `src/parcelproof/merkle.py` and the Solidity library in
`contracts/src/CustodyAnchor.sol` are separate implementations of the same specification. These
tests are what stop them from drifting: a root built in Python has to be accepted by proofs
verified in the EVM, and a tampered record has to be rejected by the contract, not just by Python.
"""

import pytest

from parcelproof import merkle
from parcelproof.events import CustodyEvent, EventType, leaf_hash
from parcelproof.ledger import Ledger

pytestmark = pytest.mark.onchain


@pytest.fixture
def anchor(chain):
    return chain.deploy("MerkleAnchor")


def sample_events(count: int) -> list[CustodyEvent]:
    return [
        CustodyEvent(
            parcel_id=f"PP{i:07d}",
            sequence=0,
            event_type=EventType.ARRIVE_FACILITY,
            actor="carrier-north",
            location="EWR-01",
            occurred_at=1_760_000_000 + i,
        )
        for i in range(count)
    ]


@pytest.mark.parametrize("count", [1, 2, 3, 5, 8, 17, 64])
def test_python_proofs_verify_inside_the_evm(chain, anchor, count):
    """Every leaf shape, including the odd counts that trigger node promotion."""
    leaves = [leaf_hash(event) for event in sample_events(count)]
    chain.send(anchor.functions.anchor(merkle.root(leaves), count))
    batch_id = anchor.functions.batchCount().call() - 1

    for index, leaf in enumerate(leaves):
        assert anchor.functions.verify(batch_id, leaf, merkle.proof(leaves, index)).call()


def test_evm_rejects_a_leaf_that_was_not_committed(chain, anchor):
    leaves = [leaf_hash(event) for event in sample_events(8)]
    chain.send(anchor.functions.anchor(merkle.root(leaves), 8))
    batch_id = anchor.functions.batchCount().call() - 1

    forged = leaf_hash(
        CustodyEvent("PP9999999", 0, EventType.DELIVERED, "carrier-air", "PHX-08", 1)
    )
    assert not anchor.functions.verify(batch_id, forged, merkle.proof(leaves, 0)).call()


def test_tampered_custody_record_is_rejected_by_the_contract(chain, anchor):
    """The end-to-end demonstration: ingest, seal, anchor, prove, tamper, and watch the chain
    refuse the proof."""
    with Ledger() as ledger:
        ids = ledger.append_many(sample_events(8))
        batch = ledger.seal_batch(sealed_at=1_760_000_100)
        assert batch is not None

        receipt = chain.send(anchor.functions.anchor(batch.root, batch.leaf_count))
        chain_batch_id = anchor.functions.batchCount().call() - 1
        ledger.record_anchor(batch.id, chain_batch_id, receipt.tx_hash)

        target = ids[3]
        before = ledger.inclusion_proof(target)
        assert anchor.functions.verify(
            chain_batch_id, leaf_hash(before.event), before.path
        ).call()

        ledger.raw_update(target, location="ONT-03")

        after = ledger.inclusion_proof(target)
        assert not anchor.functions.verify(
            chain_batch_id, leaf_hash(after.event), after.path
        ).call()


def test_unknown_batch_reverts_on_chain(chain, anchor):
    from web3.exceptions import ContractLogicError

    with pytest.raises(ContractLogicError):
        anchor.functions.verify(99, b"\x00" * 32, []).call()


def test_raw_gas_varies_only_by_the_calldata_zero_byte_discount(chain):
    """Pins down the one source of variation in an otherwise deterministic measurement.

    Two `record` calls run identical code, yet their gas differs, because a zero byte in calldata
    costs 4 gas and a non-zero byte costs 16. Event hashes are effectively random, so they contain
    different numbers of zero bytes. Removing that discount has to collapse the measurements to a
    single value; if anything else were varying, this would fail.
    """
    per_event = chain.deploy("PerEventStorage")
    receipts = [
        chain.send(per_event.functions.record(leaf_hash(event)))
        for event in sample_events(12)
    ]

    raw = {receipt.gas_used for receipt in receipts}
    normalised = {receipt.gas_at_uniform_calldata for receipt in receipts}

    assert len(raw) > 1, "expected the zero-byte discount to show up across random hashes"
    assert len(normalised) == 1, f"gas varies beyond the calldata discount: {receipts}"


def test_anchor_gas_is_constant_across_calls(chain, anchor):
    """Justifies extrapolating a whole trace from a handful of measured transactions.

    The benchmark prices tens of thousands of events from a per-call gas figure rather than by
    sending tens of thousands of transactions, so the per-call cost has to be genuinely invariant.
    The first call is excluded: it initialises the batch counter from zero, which is a more
    expensive storage write than every later update to it.
    """
    receipts = [
        chain.send(anchor.functions.anchor(merkle.root([leaf_hash(event)]), 4))
        for event in sample_events(6)
    ]
    normalised = {receipt.gas_at_uniform_calldata for receipt in receipts[1:]}

    assert len(normalised) == 1, f"anchor gas drifted across calls: {receipts}"


def test_first_anchor_costs_more_than_the_rest(chain, anchor):
    """Initialising the batch counter is a zero-to-non-zero storage write, which the EVM prices
    far above the updates that follow. The benchmark has to exclude it or it overstates cost."""
    receipts = [
        chain.send(anchor.functions.anchor(merkle.root([leaf_hash(event)]), 4))
        for event in sample_events(3)
    ]
    assert receipts[0].gas_at_uniform_calldata > receipts[1].gas_at_uniform_calldata


def test_verification_gas_grows_with_proof_depth(chain, anchor):
    """The cost side of large batches: deeper trees mean more hashes to check on-chain."""
    depths = {}
    for count in (2, 16, 256):
        leaves = [leaf_hash(event) for event in sample_events(count)]
        chain.send(anchor.functions.anchor(merkle.root(leaves), count))
        batch_id = anchor.functions.batchCount().call() - 1
        path = merkle.proof(leaves, 0)
        depths[len(path)] = chain.send(anchor.functions.verify(batch_id, leaves[0], path)).gas_used

    assert sorted(depths) == [1, 4, 8]
    assert depths[1] < depths[4] < depths[8]
