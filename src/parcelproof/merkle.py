"""Merkle tree over custody event leaves.

Must agree exactly with ``CustodyMerkle`` in ``contracts/src/CustodyAnchor.sol``. Two rules make
the tree well defined:

* **Sorted pairs.** Siblings are ordered before hashing, so an inclusion proof is just a list of
  hashes and does not need to carry a left/right bit per level.
* **Promotion, not duplication.** A level with an odd number of nodes promotes the last node
  unchanged. Duplicating it instead, which is common, lets the leaf sets ``[a, b, c]`` and
  ``[a, b, c, c]`` produce the same root.
"""

from __future__ import annotations

from .events import NODE_PREFIX, keccak256


def hash_pair(a: bytes, b: bytes) -> bytes:
    """Hash two sibling nodes, smaller value first."""
    low, high = (a, b) if a < b else (b, a)
    return keccak256(NODE_PREFIX + low + high)


def _parent_level(level: list[bytes]) -> list[bytes]:
    return [
        hash_pair(level[i], level[i + 1]) if i + 1 < len(level) else level[i]
        for i in range(0, len(level), 2)
    ]


def levels(leaves: list[bytes]) -> list[list[bytes]]:
    """Every level of the tree, leaves first, root last."""
    if not leaves:
        raise ValueError("cannot build a tree over zero leaves")
    out = [list(leaves)]
    while len(out[-1]) > 1:
        out.append(_parent_level(out[-1]))
    return out


def root(leaves: list[bytes]) -> bytes:
    return levels(leaves)[-1][0]


def proof(leaves: list[bytes], index: int) -> list[bytes]:
    """The sibling hashes needed to walk `leaves[index]` up to the root.

    Levels where the node was promoted contribute nothing, so the proof can be shorter than the
    depth of the tree.
    """
    if not 0 <= index < len(leaves):
        raise IndexError(f"leaf index {index} out of range for {len(leaves)} leaves")
    out = []
    idx = index
    for level in levels(leaves)[:-1]:
        sibling = idx ^ 1
        if sibling < len(level):
            out.append(level[sibling])
        idx //= 2
    return out


def process_proof(leaf: bytes, path: list[bytes]) -> bytes:
    """Fold a proof over a leaf to get the root it implies."""
    node = leaf
    for sibling in path:
        node = hash_pair(node, sibling)
    return node


def verify(leaf: bytes, path: list[bytes], expected_root: bytes) -> bool:
    return process_proof(leaf, path) == expected_root
