"""The off-chain custody log.

Events live here; only the Merkle root of each sealed batch goes on-chain. SQLite is deliberate:
the interesting properties of this system are cryptographic, not operational, and a single file
database lets anyone reproduce the tamper demonstration without standing up infrastructure.

Note what is *not* stored: the leaf hash. Recording it would create a second source of truth and
invite verification code to trust it. Leaves are always recomputed from the event columns, so
editing a row necessarily changes its leaf, which is the entire basis of the tamper evidence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import merkle
from .events import CustodyEvent, EventType, leaf_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batch (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    root           BLOB    NOT NULL,
    leaf_count     INTEGER NOT NULL,
    sealed_at      INTEGER NOT NULL,
    chain_batch_id INTEGER,
    tx_hash        TEXT
);

CREATE TABLE IF NOT EXISTS custody_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id   TEXT    NOT NULL,
    sequence    INTEGER NOT NULL,
    event_type  TEXT    NOT NULL,
    actor       TEXT    NOT NULL,
    location    TEXT    NOT NULL,
    occurred_at INTEGER NOT NULL,
    batch_id    INTEGER REFERENCES batch(id),
    leaf_index  INTEGER,
    UNIQUE (parcel_id, sequence)
);

CREATE INDEX IF NOT EXISTS custody_event_batch ON custody_event (batch_id, leaf_index);
CREATE INDEX IF NOT EXISTS custody_event_parcel ON custody_event (parcel_id, sequence);
"""


@dataclass(frozen=True)
class Batch:
    id: int
    root: bytes
    leaf_count: int
    sealed_at: int
    chain_batch_id: int | None = None
    tx_hash: str | None = None


@dataclass(frozen=True)
class InclusionProof:
    """Everything a verifier needs, and nothing it should have to trust.

    The verifier recomputes ``leaf_hash(event)`` itself and folds ``path`` over it. ``root`` is
    the value that was anchored when the batch was sealed, not a value derived from the current
    contents of the database.
    """

    event: CustodyEvent
    path: list[bytes]
    batch_id: int
    root: bytes
    chain_batch_id: int | None


class Ledger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def append(self, event: CustodyEvent) -> int:
        """Record a custody event as pending. Returns its ledger id."""
        cursor = self._db.execute(
            "INSERT INTO custody_event"
            " (parcel_id, sequence, event_type, actor, location, occurred_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.parcel_id,
                event.sequence,
                event.event_type.value,
                event.actor,
                event.location,
                event.occurred_at,
            ),
        )
        self._db.commit()
        return int(cursor.lastrowid)

    def append_many(self, events: list[CustodyEvent]) -> list[int]:
        return [self.append(event) for event in events]

    def pending_count(self) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) AS n FROM custody_event WHERE batch_id IS NULL"
        ).fetchone()
        return int(row["n"])

    def seal_batch(self, sealed_at: int, limit: int | None = None) -> Batch | None:
        """Build a Merkle tree over the pending events and record its root.

        Leaf order is ledger insertion order, which is the order the events were ingested.
        Returns ``None`` when there is nothing pending.
        """
        rows = self._db.execute(
            "SELECT * FROM custody_event WHERE batch_id IS NULL ORDER BY id"
            + (" LIMIT ?" if limit is not None else ""),
            (limit,) if limit is not None else (),
        ).fetchall()
        if not rows:
            return None

        leaves = [leaf_hash(_to_event(row)) for row in rows]
        cursor = self._db.execute(
            "INSERT INTO batch (root, leaf_count, sealed_at) VALUES (?, ?, ?)",
            (merkle.root(leaves), len(leaves), sealed_at),
        )
        batch_id = int(cursor.lastrowid)
        self._db.executemany(
            "UPDATE custody_event SET batch_id = ?, leaf_index = ? WHERE id = ?",
            [(batch_id, index, row["id"]) for index, row in enumerate(rows)],
        )
        self._db.commit()
        return self.batch(batch_id)

    def record_anchor(self, batch_id: int, chain_batch_id: int, tx_hash: str) -> None:
        """Attach the on-chain identity of a batch after its root has been anchored."""
        self._db.execute(
            "UPDATE batch SET chain_batch_id = ?, tx_hash = ? WHERE id = ?",
            (chain_batch_id, tx_hash, batch_id),
        )
        self._db.commit()

    def batch(self, batch_id: int) -> Batch:
        row = self._db.execute("SELECT * FROM batch WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError(f"no batch {batch_id}")
        return Batch(
            id=row["id"],
            root=row["root"],
            leaf_count=row["leaf_count"],
            sealed_at=row["sealed_at"],
            chain_batch_id=row["chain_batch_id"],
            tx_hash=row["tx_hash"],
        )

    def event(self, event_id: int) -> CustodyEvent:
        row = self._db.execute(
            "SELECT * FROM custody_event WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no custody event {event_id}")
        return _to_event(row)

    def parcel_history(self, parcel_id: str) -> list[tuple[int, CustodyEvent]]:
        rows = self._db.execute(
            "SELECT * FROM custody_event WHERE parcel_id = ? ORDER BY sequence",
            (parcel_id,),
        ).fetchall()
        return [(row["id"], _to_event(row)) for row in rows]

    def inclusion_proof(self, event_id: int) -> InclusionProof:
        """Build an inclusion proof for one event from the current contents of the batch.

        The sibling hashes come from the other events as they are stored *now*. If any row in the
        batch has been edited since it was sealed, the recomputed siblings differ and the proof
        no longer folds to the anchored root. That is why tampering with one record invalidates
        the proofs of every event batched alongside it.
        """
        row = self._db.execute(
            "SELECT batch_id, leaf_index FROM custody_event WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no custody event {event_id}")
        if row["batch_id"] is None:
            raise ValueError(f"custody event {event_id} has not been batched yet")

        batch_id, leaf_index = int(row["batch_id"]), int(row["leaf_index"])
        siblings = self._db.execute(
            "SELECT * FROM custody_event WHERE batch_id = ? ORDER BY leaf_index",
            (batch_id,),
        ).fetchall()
        leaves = [leaf_hash(_to_event(sibling)) for sibling in siblings]
        batch = self.batch(batch_id)
        return InclusionProof(
            event=_to_event(siblings[leaf_index]),
            path=merkle.proof(leaves, leaf_index),
            batch_id=batch_id,
            root=batch.root,
            chain_batch_id=batch.chain_batch_id,
        )

    def raw_update(self, event_id: int, **columns: object) -> None:
        """Edit stored event columns directly, bypassing the append path.

        This is the tamper tool. It exists so the demonstration in ``tests/test_tamper.py`` and
        `make demo` can act as a database operator with write access would, which is the threat
        anchoring is supposed to make detectable.
        """
        allowed = {"parcel_id", "sequence", "event_type", "actor", "location", "occurred_at"}
        unknown = set(columns) - allowed
        if unknown:
            raise ValueError(f"cannot update {sorted(unknown)}")
        assignments = ", ".join(f"{name} = ?" for name in columns)
        self._db.execute(
            f"UPDATE custody_event SET {assignments} WHERE id = ?",
            (*columns.values(), event_id),
        )
        self._db.commit()


def _to_event(row: sqlite3.Row) -> CustodyEvent:
    return CustodyEvent(
        parcel_id=row["parcel_id"],
        sequence=row["sequence"],
        event_type=EventType(row["event_type"]),
        actor=row["actor"],
        location=row["location"],
        occurred_at=row["occurred_at"],
    )
