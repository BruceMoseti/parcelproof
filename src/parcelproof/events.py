"""Custody events and their canonical byte encoding.

The leaf hash of an event is the only thing that ever reaches the chain, so the encoding has
to be exact. Two different events must never encode to the same bytes, or a parcel's history
could be rewritten without breaking any proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from Crypto.Hash import keccak

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def keccak256(data: bytes) -> bytes:
    digest = keccak.new(digest_bits=256)
    digest.update(data)
    return digest.digest()


class EventType(str, Enum):
    """The custody transitions a parcel can go through."""

    PICKUP = "PICKUP"
    ARRIVE_FACILITY = "ARRIVE_FACILITY"
    DEPART_FACILITY = "DEPART_FACILITY"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


@dataclass(frozen=True)
class CustodyEvent:
    """A single change of custody for one parcel."""

    parcel_id: str
    sequence: int
    event_type: EventType
    actor: str
    location: str
    occurred_at: int

    def __post_init__(self) -> None:
        if not self.parcel_id:
            raise ValueError("parcel_id must not be empty")
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")


# Fixed order. Changing it changes every leaf hash and invalidates every anchored root.
_FIELD_ORDER = ("parcel_id", "sequence", "event_type", "actor", "location", "occurred_at")


def canonical_bytes(event: CustodyEvent) -> bytes:
    """Encode an event as length prefixed UTF-8 fields.

    Every field is written as a four byte big endian length followed by its UTF-8 text. There is
    no separator character, so no field value can be crafted to look like a field boundary: an
    actor named ``"MEM-01|extra"`` cannot impersonate two fields. A delimiter based encoding, or
    JSON, would both need escaping rules to make the same guarantee.
    """
    out = bytearray()
    for name in _FIELD_ORDER:
        value = getattr(event, name)
        raw = (value.value if isinstance(value, Enum) else str(value)).encode("utf-8")
        out += len(raw).to_bytes(4, "big") + raw
    return bytes(out)


def leaf_hash(event: CustodyEvent) -> bytes:
    """The Merkle leaf for an event.

    Prefixed with a zero byte so that a leaf can never be confused with an internal node, which
    uses ``0x01``. Without the separation, an attacker could present an internal node as if it
    were a committed event. Mirrors ``CustodyMerkle.hashLeaf`` in the Solidity library.
    """
    return keccak256(LEAF_PREFIX + canonical_bytes(event))
