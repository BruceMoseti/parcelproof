"""The property the whole system exists to provide.

Once a batch root is anchored, an operator with full write access to the custody database cannot
change a delivery record without invalidating its inclusion proof. These tests act as that
operator: they edit rows directly through `Ledger.raw_update`, which bypasses the append path
entirely, and then check that verification fails.
"""

from parcelproof import merkle
from parcelproof.events import CustodyEvent, EventType, leaf_hash
from parcelproof.ledger import Ledger


def build_ledger(count: int = 8) -> tuple[Ledger, list[int], bytes]:
    """A ledger with one sealed batch. Returns the ledger, its event ids, and the anchored root."""
    ledger = Ledger()
    ids = ledger.append_many(
        [
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
    )
    batch = ledger.seal_batch(sealed_at=1_760_000_100)
    assert batch is not None
    return ledger, ids, batch.root


def verifies(ledger: Ledger, event_id: int, anchored_root: bytes) -> bool:
    """Verify exactly as an external auditor would: recompute the leaf from the record that is
    stored right now, and fold the proof over it against the root that was anchored."""
    proof = ledger.inclusion_proof(event_id)
    return merkle.verify(leaf_hash(proof.event), proof.path, anchored_root)


def test_untouched_ledger_verifies_end_to_end():
    ledger, ids, anchored_root = build_ledger()
    assert all(verifies(ledger, event_id, anchored_root) for event_id in ids)
    ledger.close()


def test_editing_a_delivery_location_breaks_its_own_proof():
    ledger, ids, anchored_root = build_ledger()
    target = ids[3]
    assert verifies(ledger, target, anchored_root)

    ledger.raw_update(target, location="ONT-03")

    assert ledger.event(target).location == "ONT-03"
    assert not verifies(ledger, target, anchored_root)
    ledger.close()


def test_editing_a_timestamp_breaks_its_own_proof():
    """Backdating a scan to hide a missed service window is the realistic version of this
    attack, and it moves the leaf by one field."""
    ledger, ids, anchored_root = build_ledger()
    target = ids[5]

    ledger.raw_update(target, occurred_at=1_759_000_000)

    assert not verifies(ledger, target, anchored_root)
    ledger.close()


def test_editing_one_record_breaks_the_proofs_of_the_whole_batch():
    """Because siblings feed the root, tampering is not contained to the row that was edited.
    An auditor checking any event in the batch detects it."""
    ledger, ids, anchored_root = build_ledger()
    ledger.raw_update(ids[6], actor="carrier-air")

    assert not any(verifies(ledger, event_id, anchored_root) for event_id in ids)
    ledger.close()


def test_reverting_the_edit_restores_verification():
    """The check responds to the current state of the data, not to a flag that got set. A
    corrected record verifies again."""
    ledger, ids, anchored_root = build_ledger()
    target = ids[2]
    original = ledger.event(target).location

    ledger.raw_update(target, location="DFW-04")
    assert not verifies(ledger, target, anchored_root)

    ledger.raw_update(target, location=original)
    assert verifies(ledger, target, anchored_root)
    ledger.close()


def test_resealing_after_tampering_cannot_launder_the_edit():
    """The obvious cover up: edit the row, then seal a fresh batch over the edited data. The new
    root is internally consistent, but it is not the root that was anchored, so the forgery is
    still visible to anyone holding the original commitment."""
    ledger, ids, anchored_root = build_ledger()
    ledger.raw_update(ids[4], location="PHX-08")

    proof = ledger.inclusion_proof(ids[4])
    laundered_root = merkle.process_proof(leaf_hash(proof.event), proof.path)

    assert merkle.verify(leaf_hash(proof.event), proof.path, laundered_root)
    assert laundered_root != anchored_root
    ledger.close()
