import pytest

from parcelproof.events import (
    LEAF_PREFIX,
    NODE_PREFIX,
    CustodyEvent,
    EventType,
    canonical_bytes,
    keccak256,
    leaf_hash,
)


def event(**overrides) -> CustodyEvent:
    fields = {
        "parcel_id": "PP0000001",
        "sequence": 0,
        "event_type": EventType.PICKUP,
        "actor": "carrier-north",
        "location": "EWR-01",
        "occurred_at": 1_760_000_000,
    }
    fields.update(overrides)
    return CustodyEvent(**fields)


def test_keccak256_matches_known_vector():
    assert (
        keccak256(b"").hex()
        == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )


def test_encoding_is_stable_across_calls():
    assert canonical_bytes(event()) == canonical_bytes(event())


@pytest.mark.parametrize(
    "field, value",
    [
        ("parcel_id", "PP0000002"),
        ("sequence", 1),
        ("event_type", EventType.DELIVERED),
        ("actor", "carrier-south"),
        ("location", "MEM-02"),
        ("occurred_at", 1_760_000_001),
    ],
)
def test_every_field_changes_the_leaf(field, value):
    """No field is decorative. Editing any one of them has to move the hash."""
    assert leaf_hash(event()) != leaf_hash(event(**{field: value}))


def test_field_values_cannot_impersonate_field_boundaries():
    """The reason for length prefixes rather than a delimiter.

    Under an encoding that joined fields with a separator, these two events would produce the
    same bytes, and a parcel could be moved to a different location without breaking its proof.
    """
    shifted = event(actor="carrier-north|EWR-01", location="")
    assert canonical_bytes(event()) != canonical_bytes(shifted)
    assert leaf_hash(event()) != leaf_hash(shifted)


def test_leaf_is_domain_separated_from_internal_nodes():
    """A leaf hash must never be constructible as an internal node hash, or an attacker could
    present an intermediate node as a committed event."""
    body = canonical_bytes(event())
    assert leaf_hash(event()) == keccak256(LEAF_PREFIX + body)
    assert leaf_hash(event()) != keccak256(NODE_PREFIX + body)


def test_rejects_empty_parcel_id():
    with pytest.raises(ValueError, match="parcel_id"):
        event(parcel_id="")


def test_rejects_negative_sequence():
    with pytest.raises(ValueError, match="sequence"):
        event(sequence=-1)
