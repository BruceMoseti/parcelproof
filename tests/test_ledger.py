import pytest

from parcelproof import merkle
from parcelproof.events import CustodyEvent, EventType, leaf_hash
from parcelproof.ledger import Ledger


def sample_events(count: int) -> list[CustodyEvent]:
    return [
        CustodyEvent(
            parcel_id=f"PP{i:07d}",
            sequence=0,
            event_type=EventType.PICKUP,
            actor="carrier-north",
            location="EWR-01",
            occurred_at=1_760_000_000 + i,
        )
        for i in range(count)
    ]


@pytest.fixture
def ledger():
    with Ledger() as instance:
        yield instance


def test_append_returns_increasing_ids(ledger):
    ids = ledger.append_many(sample_events(3))
    assert ids == sorted(ids)
    assert len(set(ids)) == 3


def test_pending_count_tracks_unbatched_events(ledger):
    assert ledger.pending_count() == 0
    ledger.append_many(sample_events(5))
    assert ledger.pending_count() == 5
    ledger.seal_batch(sealed_at=1_760_000_100)
    assert ledger.pending_count() == 0


def test_seal_batch_returns_none_when_nothing_pending(ledger):
    assert ledger.seal_batch(sealed_at=1) is None


def test_sealed_root_matches_a_tree_built_from_the_same_events(ledger):
    events = sample_events(6)
    ledger.append_many(events)
    batch = ledger.seal_batch(sealed_at=1_760_000_100)

    assert batch is not None
    assert batch.leaf_count == 6
    assert batch.root == merkle.root([leaf_hash(event) for event in events])


def test_seal_batch_respects_limit(ledger):
    ledger.append_many(sample_events(10))
    batch = ledger.seal_batch(sealed_at=1, limit=4)

    assert batch is not None
    assert batch.leaf_count == 4
    assert ledger.pending_count() == 6


def test_every_event_in_a_batch_has_a_verifiable_proof(ledger):
    ids = ledger.append_many(sample_events(9))
    batch = ledger.seal_batch(sealed_at=1_760_000_100)
    assert batch is not None

    for event_id in ids:
        proof = ledger.inclusion_proof(event_id)
        assert proof.root == batch.root
        assert merkle.verify(leaf_hash(proof.event), proof.path, proof.root)


def test_proof_for_unbatched_event_is_refused(ledger):
    event_id = ledger.append(sample_events(1)[0])
    with pytest.raises(ValueError, match="not been batched"):
        ledger.inclusion_proof(event_id)


def test_record_anchor_attaches_chain_identity(ledger):
    ledger.append_many(sample_events(2))
    batch = ledger.seal_batch(sealed_at=1)
    assert batch is not None
    assert batch.chain_batch_id is None

    ledger.record_anchor(batch.id, chain_batch_id=7, tx_hash="0xabc")
    assert ledger.batch(batch.id).chain_batch_id == 7
    assert ledger.inclusion_proof(1).chain_batch_id == 7


def test_parcel_history_is_ordered_by_sequence(ledger):
    for sequence in (2, 0, 1):
        ledger.append(
            CustodyEvent("PP0000001", sequence, EventType.ARRIVE_FACILITY, "c", "EWR-01", 1)
        )
    history = ledger.parcel_history("PP0000001")
    assert [event.sequence for _, event in history] == [0, 1, 2]


def test_duplicate_parcel_sequence_is_rejected(ledger):
    import sqlite3

    event = sample_events(1)[0]
    ledger.append(event)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.append(event)


def test_raw_update_refuses_unknown_columns(ledger):
    event_id = ledger.append(sample_events(1)[0])
    with pytest.raises(ValueError, match="cannot update"):
        ledger.raw_update(event_id, batch_id=99)


def test_unknown_ids_raise(ledger):
    with pytest.raises(KeyError):
        ledger.event(404)
    with pytest.raises(KeyError):
        ledger.batch(404)
